"""
Correct the missing Westwood location tag on July 2026 revenue.

THE ERROR
---------
Crew's July package (`Mighty Pilates_Financials_073126.xlsx`) posted our July
Saasant JE to the consolidated P&L correctly, but dropped the Westwood location
tag on that studio's block. Result:

  - Consolidated `Total Income` Jul 2026 = $795,727.55   (correct)
  - Sum of the 15 studio tabs          = $751,735.38
  - Untagged residual                  =  $43,992.17

  - WW studio tab Jul `Total Income`   = $105.08, which is `401006 Wellhub`
    only. Wellhub is Crew-sourced (it never comes through our JE), which is why
    it kept its tag while every account that DID come through our JE lost it.

Jan-Jun tie to the cent (consolidated == sum of studios), so this is July-only
and Westwood-only.

PROOF
-----
Our own July GL (`Mighty_GL_Jul2026_20260804_122614.xlsx`, Westwood tab) matches
the untagged residual account-by-account, to the cent. See WW_JUL_2026 below;
the values are lifted directly from that GL.

WHAT THIS SCRIPT DOES
---------------------
Moves the $43,992.17 from "untagged" onto the WW studio tree in
committed_actuals.json, so the dashboard and Excel model show Westwood's real
July. Consolidated is ALREADY correct and is deliberately left untouched — that
preserves the tie to Crew's package.

Sign convention (per pipeline/dashboard_update.py): per-studio `406000 Refunds`
and `407000 Discounts` are stored POSITIVE (QBO native negative is flipped);
consolidated keeps QBO native signs. The deltas below follow that convention.

STATUS: this is an OVERRIDE, not a restatement. Crew has been asked to post the
reclass. Their next package should self-correct, at which point
`update-dashboard` will produce the same numbers from source and this script
becomes a no-op — verify that and delete it.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JSON = REPO_ROOT / "dashboard" / "data" / "committed_actuals.json"
SNAPSHOT_DIR = REPO_ROOT / "data" / "financials" / "streamlit_snapshots"

MONTH = "Jul 2026"
STUDIO = "WW"

# Westwood July 2026, from Mighty_GL_Jul2026_20260804_122614.xlsx → Westwood tab.
# Refunds/Discounts sign-flipped to positive for the per-studio convention.
WW_JUL_2026 = {
    "401001 Machine": 24_624.55,
    "401002 Private Pilates": 3_614.00,
    "401003 Class Pass": 10_720.00,
    "403001 Machine Breakage": 9_200.30,
    "403003 Private Pilates Breakage": 450.00,
    "404000 Retail Sales": 1_182.00,
    "406000 Refunds": 852.75,
    "407000 Discounts": 4_945.93,
}

# Net effect on Total Income uses QBO-native signs: refunds and discounts reduce it.
NET_INCOME_EFFECT = (
    WW_JUL_2026["401001 Machine"]
    + WW_JUL_2026["401002 Private Pilates"]
    + WW_JUL_2026["401003 Class Pass"]
    + WW_JUL_2026["403001 Machine Breakage"]
    + WW_JUL_2026["403003 Private Pilates Breakage"]
    + WW_JUL_2026["404000 Retail Sales"]
    - WW_JUL_2026["406000 Refunds"]
    - WW_JUL_2026["407000 Discounts"]
)  # 43,992.17

SESSIONS_DELTA = (
    WW_JUL_2026["401001 Machine"]
    + WW_JUL_2026["401002 Private Pilates"]
    + WW_JUL_2026["401003 Class Pass"]
)  # 38,958.55

BREAKAGE_DELTA = (
    WW_JUL_2026["403001 Machine Breakage"]
    + WW_JUL_2026["403003 Private Pilates Breakage"]
)  # 9,650.30

# Roll-ups that must absorb the change. Revenue lands above every one of these,
# so each moves by the full net effect.
ROLLUP_DELTAS = {
    "401000 Sessions": SESSIONS_DELTA,
    "Total 401000 Sessions": SESSIONS_DELTA,
    "403000 Breakage Revenue": BREAKAGE_DELTA,
    "Total 403000 Breakage Revenue": BREAKAGE_DELTA,
    "Total Income": NET_INCOME_EFFECT,
    "Gross Profit": NET_INCOME_EFFECT,
    "Net Operating Income": NET_INCOME_EFFECT,
    "Net Income": NET_INCOME_EFFECT,
}

EXPECTED_UNTAGGED = 43_992.17


def main() -> None:
    data = json.loads(DASHBOARD_JSON.read_text())
    ww = data["studios"][STUDIO]["data"][MONTH]

    print("=" * 66)
    print("WESTWOOD JUL 2026 — LOCATION TAG CORRECTION")
    print("=" * 66)

    if abs(NET_INCOME_EFFECT - EXPECTED_UNTAGGED) > 0.005:
        raise SystemExit(
            f"Net effect {NET_INCOME_EFFECT:,.2f} != expected untagged "
            f"{EXPECTED_UNTAGGED:,.2f} — refusing to run."
        )

    # Guard against double-application: if WW already has Machine revenue, stop.
    if ww.get("401001 Machine", 0) != 0:
        raise SystemExit(
            f"WW {MONTH} '401001 Machine' is already "
            f"{ww['401001 Machine']:,.2f}, not 0 — correction looks already "
            "applied (or Crew re-issued the package). Refusing to double-apply."
        )

    print(f"\n  Revenue accounts (from our July GL, Westwood tab):")
    for account, delta in WW_JUL_2026.items():
        before = ww.get(account, 0.0)
        ww[account] = round(before + delta, 2)
        print(f"    {account:<40}{before:>12,.2f} → {ww[account]:>12,.2f}")

    print(f"\n  Roll-ups:")
    for row, delta in ROLLUP_DELTAS.items():
        before = ww.get(row, 0.0)
        ww[row] = round(before + delta, 2)
        print(f"    {row:<40}{before:>12,.2f} → {ww[row]:>12,.2f}")

    data.setdefault("overrides", []).append(
        {
            "applied_at": datetime.now().isoformat(),
            "scope": f"studios.{STUDIO}.data['{MONTH}']",
            "reason": (
                "Crew's Financials_073126 package dropped the Westwood location "
                "tag on the July Saasant JE. $43,992.17 sat untagged in "
                "consolidated. Reallocated to WW from our own July GL "
                "(Mighty_GL_Jul2026_20260804_122614.xlsx). Consolidated "
                "untouched — it was already correct."
            ),
            "amount": EXPECTED_UNTAGGED,
            "source": "Mighty_GL_Jul2026_20260804_122614.xlsx",
            "resolution": "Crew asked to post the reclass; expect self-correction next package.",
        }
    )
    data["_last_updated"] = datetime.now().isoformat()

    DASHBOARD_JSON.write_text(json.dumps(data, indent=2))
    snapshot = SNAPSHOT_DIR / "committed_actuals_Jul2026_WWcorrected.json"
    snapshot.write_text(json.dumps(data, indent=2))

    print(f"\n  WW {MONTH} Total Income: $105.08 → ${ww['Total Income']:,.2f}")
    print(f"\n  Written: {DASHBOARD_JSON.relative_to(REPO_ROOT)}")
    print(f"  Snapshot: {snapshot.relative_to(REPO_ROOT)}")
    print("=" * 66)


if __name__ == "__main__":
    main()
