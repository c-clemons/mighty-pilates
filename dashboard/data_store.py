"""Data persistence layer for the Mighty Pilates dashboard.

Subclass of ``empirica_core.BaseDataStore`` — the singleton, two-file
persistence (committed/overrides), migration, deep-merge (with list-concat for
loans), scenarios, and GitHub sync all come from the shared framework. This
module keeps only Mighty-specific model logic: the sales/OpEx forecast, loans,
capex, the accountant-actuals reconstruction, and forecast-month helpers.
"""

import sys
from pathlib import Path

import pandas as pd

# Add project root so `_load_actuals` can fall back to the pipeline importer.
sys.path.insert(0, str(Path(__file__).parent.parent))

from empirica_core import BaseDataStore

from dashboard.constants import (
    ACTIVE_STUDIOS, DEVELOPMENT_STUDIOS, OVERHEAD, ALL_STUDIOS,
    OPEX_CATEGORIES, PL_LABEL_MAP, STUDIO_PL_LABEL_MAP,
    PL_TO_OPEX_CATEGORY, FORECAST_MONTHS,
    month_key, parse_accountant_month,
)

DATA_DIR = Path(__file__).parent / "data"

# Keys that live in committed_actuals.json (locked, GitHub-synced)
COMMITTED_KEYS = (
    "metadata", "pl", "bs", "scf", "studios",
    "rev_rec_curves", "monthly_sales", "owner_tax_liability",
    "client_sales_forecast", "client_sales_forecast_consolidated",
    "account_mapping_extras",
)


class DataStore(BaseDataStore):
    """Singleton data layer for the Mighty Pilates dashboard.

    Two-file persistence (inherited):
      committed_actuals.json — locked state (actuals, curves, mappings).
          Git-tracked, synced to GitHub on explicit commit.
      user_overrides.json — soft state (assumptions, scenarios, capex).
          Git-ignored, ephemeral on redeploy.

    Baseline is ``data/baseline.json`` (the inherited default ``_load_baseline``).
    """

    DATA_DIR = DATA_DIR
    COMMITTED_KEYS = COMMITTED_KEYS
    MERGE_LISTS = True   # concatenate baseline+override lists (loans)
    GITHUB_REPO = "c-clemons/mighty-pilates"
    GITHUB_REPO_FILE_PATH = "dashboard/data/committed_actuals.json"

    # ------------------------------------------------------------------
    # Sales forecast
    # ------------------------------------------------------------------
    def get_sales_forecast(self) -> pd.DataFrame:
        """
        Return sales forecast as DataFrame: index=studio_code, columns=month keys.
        Combines actuals (from accountant) with forecast values.
        """
        forecast_data = self.merged.get("sales_forecast", {})
        all_months = self._get_all_months()
        studios = list(ACTIVE_STUDIOS.keys()) + list(DEVELOPMENT_STUDIOS.keys())

        rows = {}
        for studio in studios:
            row = {}
            for m in all_months:
                val = forecast_data.get(studio, {}).get(m, 0)
                row[m] = float(val) if val else 0.0
            rows[studio] = row

        df = pd.DataFrame.from_dict(rows, orient="index")
        df.columns.name = "Month"
        df.index.name = "Studio"
        return df

    def set_sales_forecast_bulk(self, df: pd.DataFrame):
        """Persist edited sales forecast. Only stores diffs from baseline."""
        if "sales_forecast" not in self.overrides:
            self.overrides["sales_forecast"] = {}

        baseline_sf = self.baseline.get("sales_forecast", {})

        for studio in df.index:
            for month in df.columns:
                new_val = float(df.loc[studio, month])
                base_val = float(baseline_sf.get(studio, {}).get(month, 0))
                if abs(new_val - base_val) > 0.01:
                    if studio not in self.overrides["sales_forecast"]:
                        self.overrides["sales_forecast"][studio] = {}
                    self.overrides["sales_forecast"][studio][month] = new_val

        self.merged = self._deep_merge(self.baseline, self.overrides)
        self.save_overrides()

    # ------------------------------------------------------------------
    # OpEx assumptions
    # ------------------------------------------------------------------
    def get_opex_assumptions(self) -> dict:
        """Return {studio: {category: {month: value}}}."""
        return self.merged.get("opex_assumptions", {})

    def set_opex_assumptions(self, studio: str, category: str, month: str, value: float):
        if "opex_assumptions" not in self.overrides:
            self.overrides["opex_assumptions"] = {}
        if studio not in self.overrides["opex_assumptions"]:
            self.overrides["opex_assumptions"][studio] = {}
        if category not in self.overrides["opex_assumptions"][studio]:
            self.overrides["opex_assumptions"][studio][category] = {}
        self.overrides["opex_assumptions"][studio][category][month] = value
        self.merged = self._deep_merge(self.baseline, self.overrides)
        self.save_overrides()

    def seed_forecast_from_actuals(self):
        """
        Auto-populate sales forecast and OpEx assumptions from actuals trailing averages.
        Uses the most recent 3 months of actuals data from the accountant P&L.
        Applies the average to all forecast months.
        """
        from dashboard.constants import OPEX_CATEGORIES, FORECAST_MONTHS
        actuals_months = self.get_actuals_months()
        if not actuals_months:
            return
        forecast_months = self.get_forecast_months()
        recent = actuals_months[-3:]  # Last 3 months

        studio_pls = self.get_actuals_studio_pls()

        # --- Studio-level P&L label → OpEx category mapping ---
        studio_expense_map = {
            "property": ["Total 700000 Property Costs", "Total for 700000 Property Costs"],
            "staff": ["Total 602000 Payroll", "Total for 602000 Payroll"],
            "utilities": ["Total 616000 Utilities", "Total for 616000 Utilities"],
            "marketing": ["Total 601000 Sales & Marketing", "Total for 601000 Sales & Marketing"],
            "professional_fees": ["Total 604000 Professional Fees", "Total for 604000 Professional Fees"],
            "admin": ["603000 Software & Web Services", "608000 Insurance",
                       "609000 Business licenses", "610000 Office Supplies & General Expense",
                       "610100 Furniture & Equipment", "611000 Shipping & postage",
                       "613000 Bank fees & Service Charges", "615000 Parking Lot Rental"],
            "travel": ["605000 Travel (Airfare/hotel/ground trans/etc)", "606000 Meals",
                        "607000 Entertainment"],
            "finance": ["506000 Merchant Account Fees", "Total Cost of goods sold",
                         "Total for Cost of goods sold", "501000 Product Cost"],
            "taxes": ["902000 Taxes Paid", "903000 Property taxes"],
            "startup": ["630000 Studio Start Up Costs"],
        }

        # Revenue labels for studio sales forecast
        revenue_labels = ["Total Income", "Total for Income"]

        opex_updates = {}
        sales_updates = {}

        for code, studio in studio_pls.items():
            sp = studio.get("data")
            if sp is None or sp.empty:
                continue

            # Extract trailing averages
            cat_avgs = {cat: 0.0 for cat in OPEX_CATEGORIES}
            rev_avg = 0.0

            for mk in recent:
                # Find the column that matches this month key
                for col in sp.columns:
                    col_mk = parse_accountant_month(col)
                    if col_mk != mk:
                        continue

                    # Revenue
                    for label in revenue_labels:
                        if label in sp.index:
                            val = sp.loc[label, col]
                            if pd.notna(val):
                                rev_avg += abs(float(val))

                    # Expenses by category
                    for cat, labels in studio_expense_map.items():
                        if cat == "taxes":
                            continue  # taxes handled at consolidated level
                        for label in labels:
                            if label in sp.index:
                                val = sp.loc[label, col]
                                if pd.notna(val):
                                    cat_avgs[cat] += abs(float(val))

            n = len(recent)
            if n > 0:
                rev_avg /= n
                for cat in cat_avgs:
                    cat_avgs[cat] /= n

            # Apply to forecast months
            if code not in opex_updates:
                opex_updates[code] = {}
            for cat, avg in cat_avgs.items():
                if avg > 0:
                    opex_updates[code][cat] = {m: round(avg, 2) for m in forecast_months}

            if rev_avg > 0:
                sales_updates[code] = {m: round(rev_avg, 2) for m in forecast_months}

        # Consolidated taxes (from consolidated P&L)
        pl = self.get_actuals_pl()
        if not pl.empty:
            tax_avg = 0
            for mk in recent:
                for col in pl.columns:
                    if parse_accountant_month(col) == mk:
                        for label in ["902000 Taxes Paid", "903000 Property taxes"]:
                            if label in pl.index:
                                val = pl.loc[label, col]
                                if pd.notna(val):
                                    tax_avg += abs(float(val))
            tax_avg /= len(recent) if recent else 1
            # Split taxes to HO (Home Office)
            if "HO" not in opex_updates:
                opex_updates["HO"] = {}
            opex_updates["HO"]["taxes"] = {m: round(tax_avg, 2) for m in forecast_months}

        # Save
        if "opex_assumptions" not in self.overrides:
            self.overrides["opex_assumptions"] = {}
        for studio, cats in opex_updates.items():
            if studio not in self.overrides["opex_assumptions"]:
                self.overrides["opex_assumptions"][studio] = {}
            for cat, months in cats.items():
                self.overrides["opex_assumptions"][studio][cat] = months

        if "sales_forecast" not in self.overrides:
            self.overrides["sales_forecast"] = {}
        for studio, months in sales_updates.items():
            if studio not in self.overrides["sales_forecast"]:
                self.overrides["sales_forecast"][studio] = {}
            self.overrides["sales_forecast"][studio].update(months)

        self.merged = self._deep_merge(self.baseline, self.overrides)
        self.save_overrides()
        return len(opex_updates), len(sales_updates)

    # ------------------------------------------------------------------
    # Loans
    # ------------------------------------------------------------------
    def get_loans(self) -> list:
        return self.merged.get("loans", [])

    def add_loan(self, loan: dict):
        if "loans" not in self.overrides:
            self.overrides["loans"] = []
        self.overrides["loans"].append(loan)
        self.merged = self._deep_merge(self.baseline, self.overrides)
        self.save_overrides()

    # ------------------------------------------------------------------
    # CapEx
    # ------------------------------------------------------------------
    def get_capex(self) -> dict:
        return self.merged.get("capex", {})

    def get_capex_projects(self) -> list:
        return self.committed.get("capex_projects", self.merged.get("capex_projects", []))

    def add_capex_project(self, project: dict):
        if "capex_projects" not in self.committed:
            self.committed["capex_projects"] = []
        self.committed["capex_projects"].append(project)
        self.merged = self._deep_merge(self.baseline, self.overrides)
        self.save_committed("add capex project: " + project.get("name", "unnamed"))

    def update_capex_project(self, idx: int, updates: dict):
        projects = self.committed.get("capex_projects", [])
        if idx < len(projects):
            projects[idx].update(updates)
            self.save_committed("update capex project")

    def remove_capex_project(self, idx: int):
        projects = self.committed.get("capex_projects", [])
        if idx < len(projects):
            projects.pop(idx)
            self.save_committed("remove capex project")

    def get_capex_by_month(self) -> dict:
        """Return {month: total_capex} for active projects only."""
        result = {}
        for proj in self.get_capex_projects():
            if proj.get("active"):
                for m, val in proj.get("schedule", {}).items():
                    result[m] = result.get(m, 0) + val
        return result

    # ------------------------------------------------------------------
    # Actuals from accountant import
    # ------------------------------------------------------------------
    def get_actuals_pl(self) -> pd.DataFrame:
        return self.actuals.get("pl", pd.DataFrame())

    def get_actuals_bs(self) -> pd.DataFrame:
        return self.actuals.get("bs", pd.DataFrame())

    def get_actuals_scf(self) -> pd.DataFrame:
        return self.actuals.get("scf", pd.DataFrame())

    def get_actuals_studio_pls(self) -> dict:
        return self.actuals.get("studios", {})

    def get_owner_tax_liability(self) -> dict:
        return self.actuals.get("owner_tax_liability", {})

    def get_forecast_ratios(self) -> dict:
        return self.actuals.get("forecast_ratios", {})

    def get_interest_schedule(self) -> dict:
        return self.actuals.get("interest_schedule", {})

    def get_rev_rec_curves(self) -> dict:
        return self.actuals.get("rev_rec_curves", {})

    def get_monthly_sales(self) -> dict:
        return self.actuals.get("monthly_sales", {})

    def get_client_sales_forecast(self) -> dict:
        """Return {studio_code: {month_key: value}} from committed_actuals.

        This is the client-confirmed source of truth for monthly gross cash
        sales per studio (both actuals and forecast). Use this in preference
        to deriving from accountant per-studio P&L (which gives recognized
        revenue, not cash collected) or the legacy baseline+overrides
        sales_forecast.
        """
        return self.actuals.get("client_sales_forecast", {})

    def get_last_actuals_month(self) -> str:
        """Return e.g. 'February 2026'."""
        meta = self.actuals.get("metadata", {})
        return meta.get("last_actuals_month", "Unknown")

    def get_last_actuals_month_key(self) -> str:
        """Return e.g. '2026-02'."""
        display = self.get_last_actuals_month()
        key = parse_accountant_month(display)
        return key or "2026-02"

    def get_actuals_months(self) -> list:
        """Return sorted list of month keys from the accountant P&L."""
        pl = self.get_actuals_pl()
        if pl.empty:
            return []
        months = []
        for col in pl.columns:
            mk = parse_accountant_month(col)
            if mk:
                months.append(mk)
        return sorted(months)

    # ------------------------------------------------------------------
    # Forecast months
    # ------------------------------------------------------------------
    def get_forecast_months(self) -> list:
        """Return list of month keys from first forecast month through horizon."""
        last = self.get_last_actuals_month_key()
        y, m = map(int, last.split("-"))
        # First forecast month is one after last actuals
        m += 1
        if m > 12:
            m = 1
            y += 1
        months = []
        for _ in range(FORECAST_MONTHS):
            months.append(month_key(y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1
        return months

    # ------------------------------------------------------------------
    # Actuals reconstruction (hook)
    # ------------------------------------------------------------------
    def _load_actuals(self):
        """Load actuals from committed_actuals.json (primary) or pipeline CSVs (local dev).

        committed_actuals.json is the source of truth on Streamlit Cloud.
        Locally, pipeline CSVs may be fresher, but committed extras are supplemented.
        """
        raw = self.committed

        # If committed file has actuals, use it
        if raw.get("pl"):
            self.actuals = {
                "metadata": raw.get("metadata", {}),
                "pl": pd.DataFrame(raw["pl"]) if raw.get("pl") else pd.DataFrame(),
                "bs": pd.DataFrame(raw["bs"]) if raw.get("bs") else pd.DataFrame(),
                "scf": pd.DataFrame(raw["scf"]) if raw.get("scf") else pd.DataFrame(),
                "owner_tax_liability": raw.get("owner_tax_liability", {}),
                "rev_rec_curves": raw.get("rev_rec_curves", {}),
                "monthly_sales": raw.get("monthly_sales", {}),
                "client_sales_forecast": raw.get("client_sales_forecast", {}),
                "client_sales_forecast_consolidated": raw.get("client_sales_forecast_consolidated", {}),
                "account_mapping_extras": raw.get("account_mapping_extras", {}),
                "forecast_ratios": raw.get("forecast_ratios", {}),
                "interest_schedule": raw.get("interest_schedule", {}),
                "adjusted_ebitda_addbacks": raw.get("adjusted_ebitda_addbacks", {}),
                "manual_financing_events": raw.get("manual_financing_events", {}),
                "studios": {},
            }
            for code, studio in raw.get("studios", {}).items():
                self.actuals["studios"][code] = {
                    "name": studio.get("name", code),
                    "data": pd.DataFrame(studio["data"]) if studio.get("data") else pd.DataFrame(),
                }
            return

        # Fallback: try pipeline CSVs (local dev)
        try:
            from pipeline.accountant_import import load_latest
            self.actuals = load_latest()
            # Supplement with committed extras
            for key in ["owner_tax_liability", "rev_rec_curves", "monthly_sales",
                        "client_sales_forecast", "client_sales_forecast_consolidated",
                        "account_mapping_extras", "forecast_ratios", "interest_schedule"]:
                if key in raw:
                    self.actuals[key] = raw[key]
            return
        except (FileNotFoundError, ImportError, Exception):
            pass

        # Nothing available
        self.actuals = {"pl": pd.DataFrame(), "bs": pd.DataFrame(),
                        "scf": pd.DataFrame(), "studios": {},
                        "metadata": {"last_actuals_month":
                                     self.baseline.get("metadata", {}).get(
                                         "last_actuals_month", "February 2026")}}

    def _get_all_months(self) -> list:
        """Return combined actuals + forecast months."""
        return self.get_actuals_months() + self.get_forecast_months()
