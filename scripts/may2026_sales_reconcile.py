"""
May 2026 sales reconciliation vs client-supplied figures.

Client report columns (per Cat's MAY summary):
  MindBody Sales  + ClassPass Revenue + Wellhub Revenue + Retail Sales = Total Sales

Data sources:
  - MindBody sales:  EARNED_REVENUE_ANALYTICS.DAILY_REVENUE_AND_SALES_DETAIL (EVENT_TYPE='Purchase')
  - ClassPass:       PLAYLIST_DATAMART.CLASSPASS_REPORTING_ANALYTICS.RESERVATIONS (separate; excluded from DAILY table)
  - Wellhub/Gympass: appears in MART_SALES_DETAILS under category 'Gympass Revenue' (none in May 2026)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from pipeline.connection import get_connection, execute_query_df

# Client-supplied figures: keyed by full canonical studio name
CLIENT = {
    "Mighty Pilates Presidio Heights": {"mb": 73046, "cp": 20465, "wh":    0, "total":  93511},
    "Mighty Pilates Marin":            {"mb": 61151, "cp": 13231, "wh":    0, "total":  74382},
    "Mighty Pilates Santa Monica":     {"mb":182594, "cp": 24038, "wh":    0, "total": 206632},
    "Mighty Pilates Lafayette":        {"mb": 58975, "cp": 12469, "wh":    0, "total":  71444},
    "Mighty Pilates Berkeley":         {"mb": 57159, "cp": 26114, "wh":    0, "total":  83273},
    "Mighty Pilates Westwood":         {"mb": 47948, "cp": 12802, "wh":    0, "total":  60750},
    "Mighty Pilates Russian Hill":     {"mb": 37997, "cp": 28860, "wh":    0, "total":  66857},
    "Mighty Pilates Ocean Park":       {"mb": 49276, "cp": 14494, "wh":    0, "total":  63770},
    "Mighty Pilates Danville":         {"mb": 10692, "cp":  4645, "wh":    0, "total":  15337},
    "Mighty Pilates Culver City":      {"mb": 28025, "cp": 15302, "wh":    0, "total":  43327},
    "Mighty Pilates West Portal":      {"mb":    26, "cp":     0, "wh":    0, "total":     26},
    "Mighty Pilates Santa Barbara":    {"mb": 11647, "cp":  8486, "wh":    0, "total":  20133},
}

SQL_MB = """
SELECT STUDIO_NAME, SUM(NET_TOTAL_SALES) AS NET_SALES
FROM EARNED_REVENUE_ANALYTICS.DAILY_REVENUE_AND_SALES_DETAIL
WHERE EVENT_TYPE = 'Purchase'
  AND EVENT_DATE >= '2026-05-01' AND EVENT_DATE < '2026-06-01'
GROUP BY 1 ORDER BY 1
"""

SQL_CP = """
SELECT EARNED_REVENUE_ANALYTICS.CANON_STUDIO(VENUE_FULL_NAME) AS STUDIO_NAME,
       SUM(RATE) AS CP_REVENUE
FROM PLAYLIST_DATAMART.CLASSPASS_REPORTING_ANALYTICS.RESERVATIONS
WHERE START_DATE >= '2026-05-01' AND START_DATE < '2026-06-01'
  AND RATE > 0
GROUP BY 1 ORDER BY 1
"""

SQL_WH = """
SELECT STUDIO_NAME, SUM(NET_TOTAL_SALES) AS WH_REVENUE
FROM EARNED_REVENUE_ANALYTICS.DAILY_REVENUE_AND_SALES_DETAIL
WHERE EVENT_TYPE = 'Purchase'
  AND EVENT_DATE >= '2026-05-01' AND EVENT_DATE < '2026-06-01'
  AND (REVENUE_CATEGORY ILIKE '%gympass%' OR REVENUE_CATEGORY ILIKE '%wellhub%')
GROUP BY 1 ORDER BY 1
"""

def main():
    conn = get_connection()
    try:
        mb = execute_query_df(conn, SQL_MB)
        cp = execute_query_df(conn, SQL_CP)
        wh = execute_query_df(conn, SQL_WH)
    finally:
        conn.close()

    mb_d = dict(zip(mb["STUDIO_NAME"], mb["NET_SALES"].astype(float)))
    cp_d = dict(zip(cp["STUDIO_NAME"], cp["CP_REVENUE"].astype(float))) if not cp.empty else {}
    wh_d = dict(zip(wh["STUDIO_NAME"], wh["WH_REVENUE"].astype(float))) if not wh.empty else {}

    print("\n=== May 2026 Sales Reconciliation ===\n")
    cols = f"{'Studio':<32} {'MB Ours':>11} {'MB Client':>11} {'Δ':>9} | {'CP Ours':>10} {'CP Client':>10} {'Δ':>9} | {'Tot Ours':>11} {'Tot Client':>11} {'Δ':>9}"
    print(cols)
    print("-"*len(cols))
    g = dict(mb_o=0,mb_c=0,cp_o=0,cp_c=0,t_o=0,t_c=0)
    for studio, v in CLIENT.items():
        mb_o = mb_d.get(studio, 0.0)
        cp_o = cp_d.get(studio, 0.0)
        wh_o = wh_d.get(studio, 0.0)
        t_o = mb_o + cp_o + wh_o
        mb_c = v["mb"]; cp_c = v["cp"]; t_c = v["total"]
        g["mb_o"] += mb_o; g["mb_c"] += mb_c
        g["cp_o"] += cp_o; g["cp_c"] += cp_c
        g["t_o"]  += t_o;  g["t_c"]  += t_c
        short = studio.replace("Mighty Pilates ", "")
        print(f"{short:<32} {mb_o:>11,.0f} {mb_c:>11,.0f} {mb_o-mb_c:>9,.0f} | "
              f"{cp_o:>10,.0f} {cp_c:>10,.0f} {cp_o-cp_c:>9,.0f} | "
              f"{t_o:>11,.0f} {t_c:>11,.0f} {t_o-t_c:>9,.0f}")
    print("-"*len(cols))
    print(f"{'TOTAL':<32} {g['mb_o']:>11,.0f} {g['mb_c']:>11,.0f} {g['mb_o']-g['mb_c']:>9,.0f} | "
          f"{g['cp_o']:>10,.0f} {g['cp_c']:>10,.0f} {g['cp_o']-g['cp_c']:>9,.0f} | "
          f"{g['t_o']:>11,.0f} {g['t_c']:>11,.0f} {g['t_o']-g['t_c']:>9,.0f}")

if __name__ == "__main__":
    main()
