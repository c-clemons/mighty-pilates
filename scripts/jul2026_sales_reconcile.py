"""
July 2026 sales reconciliation vs Cat-supplied figures.

Cat's JULY summary gave two columns per studio:
  ClassPass  +  (everything else: MindBody sales)  =  Total Sales
So the implied non-ClassPass ("MB-side") figure = Total - ClassPass.

DATA-SOURCE NOTE (2026-08-04):
  The curated EARNED_REVENUE_ANALYTICS.DAILY_REVENUE_AND_SALES_DETAIL table that the
  May/Jun reconciles used is only loaded through 2026-07-07 — STALE for July. Per the
  runbook we reconcile the MB-side against raw MART_SALES_DETAILS (loaded through 7/31).
  On the last complete month (May) DAILY.NET_TOTAL_SALES ($626,479) ties to
  MART.NET_PAYMENTAMT_LOCAL ($623,794, +0.43%), so NET_PAYMENTAMT_LOCAL is the
  MB-side column. NET_CASH is reported alongside for reference.

  ClassPass rows exist in MART but carry $0 revenue; ClassPass $ lives in RESERVATIONS.
  RESERVATIONS is ALSO lagging — loaded only through 2026-07-26 — so the ClassPass
  column will read ~$28-30K light vs Cat. That is a load lag, NOT a real discrepancy.

Sources:
  - MB-side:   PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS
  - ClassPass: PLAYLIST_DATAMART.CLASSPASS_REPORTING_ANALYTICS.RESERVATIONS

Flag any per-studio or per-category MB-side delta >= $1,000 to Cat before proceeding.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from pipeline.connection import get_connection, execute_query_df

FLAG_THRESHOLD = 1000
START, END = "2026-07-01", "2026-08-01"

# Cat-supplied figures: keyed by full canonical studio name.
# Cat gave ClassPass ("cp") and Total ("total"); implied MB-side = total - cp.
CLIENT = {
    "Mighty Pilates Presidio Heights": {"cp": 19210, "total": 117515},
    "Mighty Pilates Marin":            {"cp": 13483, "total": 109856},
    "Mighty Pilates Santa Monica":     {"cp": 26558, "total": 163688},
    "Mighty Pilates Lafayette":        {"cp": 10615, "total":  86878},
    "Mighty Pilates Berkeley":         {"cp": 22681, "total":  99551},
    "Mighty Pilates Westwood":         {"cp": 10720, "total":  47537},
    "Mighty Pilates Russian Hill":     {"cp": 25557, "total":  75936},
    "Mighty Pilates Ocean Park":       {"cp": 14609, "total":  58162},
    "Mighty Pilates Danville":         {"cp":  4806, "total":  16795},
    "Mighty Pilates Culver City":      {"cp": 16616, "total":  42903},
    "Mighty Pilates West Portal":      {"cp":     0, "total":     99},
    "Mighty Pilates Santa Barbara":    {"cp":  6589, "total":  18714},
}

SQL_MART = f"""
SELECT STUDIO_NAME,
       SUM(NET_PAYMENTAMT_LOCAL) AS NET_PAY,
       SUM(NET_CASH)             AS NET_CASH
FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS
WHERE SALE_DATE >= '{START}' AND SALE_DATE < '{END}'
GROUP BY 1 ORDER BY 1
"""

SQL_MART_CAT = f"""
SELECT STUDIO_NAME, REVENUE_CATEGORY,
       SUM(NET_PAYMENTAMT_LOCAL) AS NET_PAY
FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS
WHERE SALE_DATE >= '{START}' AND SALE_DATE < '{END}'
GROUP BY 1, 2
"""

SQL_CP = f"""
SELECT EARNED_REVENUE_ANALYTICS.CANON_STUDIO(VENUE_FULL_NAME) AS STUDIO_NAME,
       SUM(RATE)     AS CP_REVENUE,
       MAX(START_DATE) AS CP_MAX_DATE
FROM PLAYLIST_DATAMART.CLASSPASS_REPORTING_ANALYTICS.RESERVATIONS
WHERE START_DATE >= '{START}' AND START_DATE < '{END}'
  AND RATE > 0
GROUP BY 1 ORDER BY 1
"""


def main():
    conn = get_connection()
    try:
        mart = execute_query_df(conn, SQL_MART)
        martc = execute_query_df(conn, SQL_MART_CAT)
        cp = execute_query_df(conn, SQL_CP)
    finally:
        conn.close()

    pay_d = dict(zip(mart["STUDIO_NAME"], mart["NET_PAY"].astype(float)))
    cash_d = dict(zip(mart["STUDIO_NAME"], mart["NET_CASH"].astype(float)))
    cp_d = dict(zip(cp["STUDIO_NAME"], cp["CP_REVENUE"].astype(float))) if not cp.empty else {}
    cp_max = str(cp["CP_MAX_DATE"].max()) if not cp.empty else "n/a"

    print("\n" + "=" * 100)
    print("July 2026 Sales Reconciliation  —  Cat vs MindBody (MART_SALES_DETAILS)")
    print("=" * 100)
    print(f"MB-side = MART NET_PAYMENTAMT_LOCAL (non-ClassPass).  Cat MB-side implied = Total - ClassPass.")
    print(f"ClassPass source RESERVATIONS loaded only through {cp_max} (Cat is full-month) — CP will read light.\n")

    cols = (f"{'Studio':<18} "
            f"{'MB Ours':>11} {'MB Cat':>11} {'Δ MB':>9} F | "
            f"{'CP Ours':>10} {'CP Cat':>10} {'Δ CP':>9} | "
            f"{'Tot Ours':>11} {'Tot Cat':>11} {'Δ Tot':>9}")
    print(cols)
    print("-" * len(cols))
    g = dict(mb_o=0, mb_c=0, cp_o=0, cp_c=0, t_o=0, t_c=0, cash_o=0)
    mb_flags = []
    for studio, v in CLIENT.items():
        mb_o = pay_d.get(studio, 0.0)
        cash_o = cash_d.get(studio, 0.0)
        cp_o = cp_d.get(studio, 0.0)
        t_o = mb_o + cp_o
        cp_c = v["cp"]; t_c = v["total"]; mb_c = t_c - cp_c
        g["mb_o"] += mb_o; g["mb_c"] += mb_c; g["cash_o"] += cash_o
        g["cp_o"] += cp_o; g["cp_c"] += cp_c
        g["t_o"] += t_o;  g["t_c"] += t_c
        short = studio.replace("Mighty Pilates ", "")
        d_mb, d_cp, d_t = mb_o - mb_c, cp_o - cp_c, t_o - t_c
        f = "<<" if abs(d_mb) >= FLAG_THRESHOLD else "  "
        if abs(d_mb) >= FLAG_THRESHOLD:
            mb_flags.append((short, d_mb, mb_o, mb_c))
        print(f"{short:<18} "
              f"{mb_o:>11,.0f} {mb_c:>11,.0f} {d_mb:>9,.0f} {f}| "
              f"{cp_o:>10,.0f} {cp_c:>10,.0f} {d_cp:>9,.0f} | "
              f"{t_o:>11,.0f} {t_c:>11,.0f} {d_t:>9,.0f}")
    print("-" * len(cols))
    print(f"{'TOTAL':<18} "
          f"{g['mb_o']:>11,.0f} {g['mb_c']:>11,.0f} {g['mb_o']-g['mb_c']:>9,.0f}   | "
          f"{g['cp_o']:>10,.0f} {g['cp_c']:>10,.0f} {g['cp_o']-g['cp_c']:>9,.0f} | "
          f"{g['t_o']:>11,.0f} {g['t_c']:>11,.0f} {g['t_o']-g['t_c']:>9,.0f}")
    print(f"\n(For reference, MART NET_CASH MB-side total = ${g['cash_o']:,.0f}, "
          f"vs NET_PAYMENTAMT ${g['mb_o']:,.0f}.)")

    print(f"\n=== MB-side flags (|Δ| >= ${FLAG_THRESHOLD:,}) ===")
    if not mb_flags:
        print("  None — MB-side reconciliation clean at $1K threshold.")
    else:
        for short, d, o, c in sorted(mb_flags, key=lambda x: -abs(x[1])):
            print(f"  {short:<18} Δ={d:>+11,.0f}   (ours ${o:>11,.0f}  vs Cat ${c:>11,.0f})")
        print("\n  Per-category MART breakdown for flagged studios:")
        for short, d, o, c in sorted(mb_flags, key=lambda x: -abs(x[1])):
            full = "Mighty Pilates " + short
            sub = martc[martc["STUDIO_NAME"] == full].copy()
            sub = sub[sub["NET_PAY"].astype(float) != 0].sort_values("NET_PAY", ascending=False)
            print(f"\n  {short}:")
            for _, row in sub.iterrows():
                print(f"     {row['REVENUE_CATEGORY']:<32} {float(row['NET_PAY']):>12,.0f}")


if __name__ == "__main__":
    main()
