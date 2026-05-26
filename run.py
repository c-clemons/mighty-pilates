#!/usr/bin/env python3
"""
Mighty Pilates Revenue Recognition Pipeline

Usage:
    python run.py test                              # Test Snowflake connection
    python run.py model                             # Run revenue recognition model
    python run.py freeze --month 2026-02            # Freeze a month's visit assignments
    python run.py close-month --month 2026-02       # Full month-end close (model + freeze + re-run)
    python run.py export                            # Generate prior month GL + Saasant exports
    python run.py export --ytd                      # Generate YTD GL export
    python run.py send                              # Generate exports and email them
    python run.py monthly                           # Full monthly workflow (close + export + send)
"""

import argparse
import sys
from datetime import datetime
from pipeline.connection import get_connection


def cmd_test(args):
    from pipeline.connection import execute_query_df
    conn = get_connection()
    print("Connected to Snowflake!")
    df = execute_query_df(conn, "SELECT CURRENT_USER() AS USER, CURRENT_ROLE() AS ROLE")
    print(df.to_string(index=False))
    conn.close()


def cmd_model(args):
    from pipeline.run_model import run_revenue_model
    conn = get_connection()
    run_revenue_model(conn)
    conn.close()


def cmd_freeze(args):
    from pipeline.run_model import freeze_month
    import calendar
    year, month = map(int, args.month.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    month_end = f"{year}-{month:02d}-{last_day:02d}"

    conn = get_connection()
    freeze_month(conn, month_end)
    conn.close()


def cmd_close_month(args):
    from pipeline.run_model import close_month
    year, month = map(int, args.month.split("-"))
    conn = get_connection()
    close_month(conn, year, month)
    conn.close()


def cmd_export(args):
    from pipeline.gl_export import generate_prior_month_gl, generate_ytd_gl
    from pipeline.saasant_export import generate_prior_month_saasant
    conn = get_connection()

    files = []
    if args.ytd:
        files.append(generate_ytd_gl(conn))
    else:
        files.append(generate_prior_month_gl(conn))

    files.append(generate_prior_month_saasant(conn))
    conn.close()

    print(f"\nGenerated {len(files)} files:")
    for f in files:
        print(f"  {f}")
    return files


def cmd_deep_dive(args):
    from reports.deep_dive import generate_prior_month_deep_dive, generate_deep_dive
    conn = get_connection()
    if args.start and args.end:
        excel_path, pdf_path = generate_deep_dive(conn, args.start, args.end)
    else:
        excel_path, pdf_path = generate_prior_month_deep_dive(conn)
    conn.close()
    print(f"\nDeep dive Excel: {excel_path}")
    print(f"Deep dive PDF:   {pdf_path}")
    return excel_path, pdf_path


def cmd_membership(args):
    from reports.membership_churn import generate_membership_report
    conn = get_connection()
    filepath = generate_membership_report(conn)
    conn.close()
    print(f"\nMembership report: {filepath}")
    return filepath


def cmd_instructor(args):
    from reports.instructor_performance import generate_instructor_report
    conn = get_connection()
    filepath = generate_instructor_report(conn)
    conn.close()
    print(f"\nInstructor report: {filepath}")
    return filepath


def cmd_client(args):
    from reports.client_lifecycle import generate_client_lifecycle_report
    conn = get_connection()
    filepath = generate_client_lifecycle_report(conn)
    conn.close()
    print(f"\nClient lifecycle report: {filepath}")
    return filepath


def cmd_send(args):
    from pipeline.distribute import send_reports
    files = cmd_export(args)
    send_reports(files)


def cmd_import_financials(args):
    """Import accountant's monthly financial package."""
    from pipeline.accountant_import import import_financials, print_summary
    result = import_financials(args.file)
    print_summary(result)


def cmd_freeze_gl(args):
    """Freeze monthly GL totals (bit-exact reproducibility)."""
    from pipeline.frozen_gl import freeze_from_live, freeze_from_saasant_file, is_month_frozen
    from pipeline.saasant_export import SERVICE_TYPE_BUCKETS

    year, month = map(int, args.month.split("-"))
    month_ym = f"{year}-{month:02d}"

    conn = get_connection()
    if args.from_file:
        rows = freeze_from_saasant_file(
            conn, args.from_file, month_ym,
            bucket_dict=SERVICE_TYPE_BUCKETS, force=args.force,
        )
        print(f"Froze {rows} GL rows for {month_ym} from {args.from_file}")
    else:
        if is_month_frozen(conn, month_ym) and not args.force:
            print(f"{month_ym} is already frozen. Use --force to re-freeze.")
            conn.close()
            return
        result = freeze_from_live(conn, year, month, force=args.force)
        print(f"Generated: {result['saasant_path']}")
        print(f"Froze {result['rows_frozen']} GL rows for {month_ym}")
    conn.close()


def cmd_monthly(args):
    """Full monthly workflow: close prior month + generate exports + email."""
    from pipeline.run_model import close_month
    from pipeline.gl_export import generate_prior_month_gl
    from pipeline.saasant_export import generate_prior_month_saasant
    from pipeline.distribute import send_reports

    today = datetime.now()
    # Default to prior month if not specified
    if args.month:
        year, month = map(int, args.month.split("-"))
    else:
        first_of_month = today.replace(day=1)
        from datetime import timedelta
        last_prior = first_of_month - timedelta(days=1)
        year, month = last_prior.year, last_prior.month

    print(f"\n{'='*60}")
    print(f"FULL MONTHLY WORKFLOW: {year}-{month:02d}")
    print(f"{'='*60}\n")

    conn = get_connection()

    # Step 1: Close the month
    print("PHASE 1: Month-end close")
    close_month(conn, year, month)

    # Step 2: Generate exports
    print("\nPHASE 2: Generate exports")
    gl_file = generate_prior_month_gl(conn)
    saasant_file = generate_prior_month_saasant(conn)

    conn.close()

    # Step 3: Distribute
    print("\nPHASE 3: Distribute")
    files = [gl_file, saasant_file]
    send_reports(files)

    print(f"\n{'='*60}")
    print(f"Monthly workflow complete for {year}-{month:02d}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Mighty Pilates Revenue Pipeline")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("test", help="Test Snowflake connection")
    sub.add_parser("model", help="Run revenue recognition model")

    p_freeze = sub.add_parser("freeze", help="Freeze a month's visit assignments")
    p_freeze.add_argument("--month", required=True, help="YYYY-MM (e.g., 2026-02)")

    p_close = sub.add_parser("close-month", help="Full month-end close")
    p_close.add_argument("--month", required=True, help="YYYY-MM (e.g., 2026-02)")

    p_dive = sub.add_parser("deep-dive", help="Generate deep dive analytics")
    p_dive.add_argument("--start", help="YYYY-MM-DD (defaults to prior month)")
    p_dive.add_argument("--end", help="YYYY-MM-DD (defaults to prior month)")

    sub.add_parser("membership", help="Membership & churn analytics")
    sub.add_parser("instructor", help="Instructor performance report")
    sub.add_parser("client", help="Client lifecycle & LTV report")

    p_export = sub.add_parser("export", help="Generate exports")
    p_export.add_argument("--ytd", action="store_true", help="YTD instead of prior month")

    p_send = sub.add_parser("send", help="Generate exports and email")
    p_send.add_argument("--ytd", action="store_true")

    p_import = sub.add_parser("import-financials", help="Import accountant's financial package")
    p_import.add_argument("file", help="Path to accountant's Excel file")

    p_fgl = sub.add_parser("freeze-gl", help="Freeze monthly GL totals (bit-exact)")
    p_fgl.add_argument("--month", required=True, help="YYYY-MM")
    p_fgl.add_argument("--from-file", help="Freeze from an existing Saasant Excel file (e.g. Rasa's booked file). Otherwise generates a live Saasant export and freezes that.")
    p_fgl.add_argument("--force", action="store_true", help="Overwrite if month is already frozen")

    p_monthly = sub.add_parser("monthly", help="Full monthly workflow")
    p_monthly.add_argument("--month", help="YYYY-MM (defaults to prior month)")

    args = parser.parse_args()

    commands = {
        "test": cmd_test,
        "model": cmd_model,
        "freeze": cmd_freeze,
        "freeze-gl": cmd_freeze_gl,
        "close-month": cmd_close_month,
        "deep-dive": cmd_deep_dive,
        "membership": cmd_membership,
        "instructor": cmd_instructor,
        "client": cmd_client,
        "import-financials": cmd_import_financials,
        "export": cmd_export,
        "send": cmd_send,
        "monthly": cmd_monthly,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
