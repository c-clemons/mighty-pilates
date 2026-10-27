# Marketing ROI + membership price increase analysis (Oct 2026)

One-off analysis for Cat's request of 2026-10-09. Read-only against Snowflake
(session temp tables only). Run from a scratch working directory; every script
reads and writes pickles/JSON in the current directory.

Order:
1. `mkt.py <2025 package.xlsx> <latest package.xlsx>` - marketing spend by studio -> `mkt.json`
2. `pull.py`, then `pull_extra.py` - build the cohort base tables (reusing
   `reports/cohort_analysis._build_base_tables`) and dump client-level extracts.
3. `base.py` - shared definitions (new client = first paid Pricing Option purchase)
4. `roi.py` - per-client LTV / retention, Q4 2025 studio table
5. `price.py` .. `price4.py` - member billing panel, Feb-2026 vs Feb-2025 cohorts,
   tenure-matched counterfactual, bootstrap elasticity
6. `report_template.html` - the published page; `__DATA__` is replaced with `data.json`
