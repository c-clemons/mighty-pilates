"""
Data persistence layer for the Mighty Pilates dashboard.
Singleton DataStore manages baseline data, user overrides, and accountant actuals.
"""

import json
import copy
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add project root for pipeline imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.constants import (
    ACTIVE_STUDIOS, DEVELOPMENT_STUDIOS, OVERHEAD, ALL_STUDIOS,
    OPEX_CATEGORIES, PL_LABEL_MAP, STUDIO_PL_LABEL_MAP,
    PL_TO_OPEX_CATEGORY, FORECAST_MONTHS,
    month_key, parse_accountant_month,
)

DATA_DIR = Path(__file__).parent / "data"


class DataStore:
    """Singleton data layer. Merges baseline + user overrides + accountant actuals."""

    _instance = None

    @classmethod
    def get(cls) -> "DataStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.baseline = {}
        self.overrides = {}
        self.merged = {}
        self.actuals = {}
        self._loaded = False

    def load(self):
        """Load baseline, overrides, and accountant actuals."""
        self.baseline = self._load_json(DATA_DIR / "baseline.json")
        self.overrides = self._load_json(DATA_DIR / "user_overrides.json")
        self.merged = self._deep_merge(self.baseline, self.overrides)
        self._load_actuals()
        self._loaded = True

    def reload(self):
        """Force reload from disk."""
        self._loaded = False
        self.load()

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
    # Scenarios
    # ------------------------------------------------------------------
    def save_scenario(self, name: str):
        """Save current overrides as a named scenario."""
        scenario_dir = DATA_DIR / "scenarios"
        scenario_dir.mkdir(parents=True, exist_ok=True)
        data = copy.deepcopy(self.overrides)
        data["_scenario_name"] = name
        data["_saved_at"] = datetime.now().isoformat()
        self._save_json(scenario_dir / f"{name}.json", data)

    def load_scenario(self, name: str):
        """Load a named scenario, replacing current overrides."""
        path = DATA_DIR / "scenarios" / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Scenario '{name}' not found")
        self.overrides = self._load_json(path)
        self.merged = self._deep_merge(self.baseline, self.overrides)
        self.save_overrides()

    def list_scenarios(self) -> list:
        """List saved scenario names with metadata."""
        scenario_dir = DATA_DIR / "scenarios"
        if not scenario_dir.exists():
            return []
        scenarios = []
        for f in sorted(scenario_dir.glob("*.json")):
            data = self._load_json(f)
            scenarios.append({
                "name": f.stem,
                "saved_at": data.get("_saved_at", "Unknown"),
            })
        return scenarios

    def delete_scenario(self, name: str):
        path = DATA_DIR / "scenarios" / f"{name}.json"
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save_overrides(self):
        self.overrides["_last_updated"] = datetime.now().isoformat()
        self._save_json(DATA_DIR / "user_overrides.json", self.overrides)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _load_actuals(self):
        """Load accountant actuals via pipeline.accountant_import if available."""
        try:
            from pipeline.accountant_import import load_latest
            self.actuals = load_latest()
        except (FileNotFoundError, ImportError, Exception):
            # Graceful fallback when running without pipeline (e.g., Streamlit Cloud)
            self.actuals = {"pl": pd.DataFrame(), "bs": pd.DataFrame(),
                            "scf": pd.DataFrame(), "studios": {},
                            "metadata": {"last_actuals_month":
                                         self.baseline.get("metadata", {}).get(
                                             "last_actuals_month", "February 2026")}}

    def _get_all_months(self) -> list:
        """Return combined actuals + forecast months."""
        return self.get_actuals_months() + self.get_forecast_months()

    @staticmethod
    def _load_json(path: Path) -> dict:
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    @staticmethod
    def _save_json(path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Recursively merge override into base. Override wins for scalars."""
        result = copy.deepcopy(base)
        for key, val in override.items():
            if key.startswith("_"):
                continue
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = DataStore._deep_merge(result[key], val)
            elif key in result and isinstance(result[key], list) and isinstance(val, list):
                # For lists (loans), append overrides to baseline
                result[key] = result[key] + val
            else:
                result[key] = copy.deepcopy(val)
        return result
