# Mighty Pilates Revenue Recognition Pipeline

## Start here

**If you're a new Claude session picking up this project, read in this order:**

1. **`docs/SESSION_NOTES.md`** — running log of work sessions, latest at top. Tells you what was done and why.
2. **`docs/DECISIONS.md`** — categorization, recognition, and policy decisions (with rationale and SQL/code refs).
3. **`docs/BACKLOG.md`** — open items and known issues that aren't blocking close.
4. **`MONTHLY_CLOSE.md`** — canonical step-by-step procedure for the monthly revenue close.

This file (CLAUDE.md) is the static project reference — codebase structure, conventions, and CLI surface.

## Overview
Revenue recognition pipeline and financial analytics for Mighty Pilates (legal entity: Norbrook Lifestyle LLC). Built for Chandler Clemons' fractional CFO engagement via Empirica Analytics. The pipeline connects to Snowflake, processes revenue data from MinBody/ClassPass, and produces GL exports for the accounting team (Crew Finance).

## Project Structure
```
mighty-pilates/
  CLAUDE.md               # THIS FILE — project conventions + CLI surface
  MONTHLY_CLOSE.md        # Canonical procedure for the monthly close
  docs/
    SESSION_NOTES.md      # Running log of work sessions (append, newest at top)
    DECISIONS.md          # Categorization / recognition / policy decisions
    BACKLOG.md            # Open items, known issues, future work
  run.py                  # CLI entry point — all commands listed below
  pipeline/
    connection.py         # Snowflake connectivity (key-pair auth)
    run_model.py          # Revenue recognition model + month-end close
    gl_export.py          # GL export workbook generation
    saasant_export.py     # QuickBooks journal entry (Saasant) export
    frozen_gl.py          # Read/write FROZEN_MONTHLY_GL for bit-exact reproducibility
    distribute.py         # Email distribution (test/production modes, hard-coded recipients)
    accountant_import.py  # Import accountant's monthly financial package
  reports/
    monthly_close_report.py    # Monthly Close Report PDF — MoM + sale-month waterfall
    deep_dive.py               # Usage & breakage analytics (Excel + PDF)
    client_lifecycle.py        # Client LTV and lifecycle stages
    membership_churn.py        # Membership churn analytics
    instructor_performance.py  # Instructor performance metrics
  sql/
    revenue_recognition.sql               # Core rev rec model logic
    visit_linking_registry.sql            # Visit-to-package assignment tracking
    hard_coded_medians.sql                # Reference duration data
    PROPOSED_visit_expiration_filter.sql  # Drafted-not-applied patch (see BACKLOG)
  scripts/
    may2026_sales_reconcile.py        # Reconciliation template (copy/update each month)
    mtt_reclass_2026.py               # One-off generator for the 2026-06-16 MTT reclass
    validate_expiration_filter.py     # Diagnostic: visits past package expiration
  snapshots/
    excel/                  # Monthly Excel snapshots (live file is on Desktop)
  config/                 # Snowflake creds & email config (gitignored)
  data/                   # Imported financial data (gitignored)
  outputs/                # Generated reports (gitignored)
```

## CLI Commands
```bash
# Snowflake / Revenue Recognition
python run.py test                          # Test Snowflake connection
python run.py model                         # Run revenue recognition model
python run.py freeze --month 2026-02        # Freeze a month's visit assignments
python run.py close-month --month 2026-02   # Full month-end close (model + freeze + re-run)
python run.py freeze-gl --month 2026-02     # Freeze monthly GL totals (bit-exact reproducibility)

# Exports & Distribution
python run.py export                        # Generate prior month GL + Saasant exports
python run.py export --ytd                  # Generate YTD GL export
python run.py close-report --month 2026-05  # Monthly Close Report PDF (MoM + waterfall)
python run.py send                          # Generate exports and email (TEST mode default)
python run.py send --production             # Same, send to client distro
python run.py monthly --month 2026-05       # Full workflow (close + export + close-report + email)
python run.py monthly --month 2026-05 --production --skip-close  # Production after test approval

# Accountant Financial Import (Stage 1)
python run.py import-financials <path>      # Import accountant's Excel package
                                            # → data/financials/{pl,bs,scf}_<Mon><Year>.csv

# Dashboard update (Stage 2)
python run.py update-dashboard --month YYYY-MM
                                            # → dashboard/data/committed_actuals.json
                                            # → snapshots to data/financials/streamlit_snapshots/

# Excel refresh (Stage 3) — runs from the financial-modeling repo
# python /Users/chandlerclemons/financial-modeling/models/mighty/refresh_from_streamlit.py

# Analytics Reports
python run.py deep-dive                     # Prior month usage & breakage analytics
python run.py deep-dive --start YYYY-MM-DD --end YYYY-MM-DD  # Custom date range
python run.py membership                    # Membership & churn analytics
python run.py instructor                    # Instructor performance report
python run.py client                        # Client lifecycle & LTV report
```

## Email Mode Safety

`pipeline/distribute.py` enforces **test-mode by default**. Production requires explicit `--production` flag.
- `PRODUCTION_RECIPIENTS` is a hard-coded list in code (not YAML — can't be accidentally edited).
- `PRODUCTION_CC` ensures Chandler's gmail gets a copy of every client send.
- `TEST_RECIPIENTS` = chandler.clemons@gmail.com only.
- Auth runs as `chandler@empirica-analytics.com` (Workspace app password); display From and Reply-To are configurable in YAML.

## Monthly Close Workflow
1. **Revenue Recognition**: `python run.py monthly --month YYYY-MM` (runs model, freezes visit assignments, generates GL + Saasant exports, emails to accounting team)
2. **Import Accountant Package**: When Crew Finance sends the monthly financials Excel, run `python run.py import-financials <path-to-file>`
3. **Analytics**: Run deep-dive, membership, instructor, or client reports as needed

## Accountant Financial Import Details

### Source Format
The accounting team (Crew Finance — Rasa Silverman, Vy Nguyen) delivers a monthly Excel file with this structure:
- **Locations** tab: Maps location names to 2-3 letter codes
- **PL** tab: Consolidated Profit & Loss (monthly columns, Jan 2025 onward)
- **BS** tab: Consolidated Balance Sheet (monthly snapshots)
- **SCF** tab: Statement of Cash Flows (monthly columns)
- **Studio tabs** (BK, CC, DN, etc.): Per-studio P&L mirroring consolidated row structure

File naming convention: `Mighty Pilates_Financials_MMDDYY Final.xlsx`

### Parser Behavior
- Auto-detects period from row 3 header and month columns in row 5
- Skips the "Total" column
- Handles sparse data for placeholder/new studios gracefully
- Saves structured CSVs to `data/financials/` with month tags (e.g., `pl_Feb2026.csv`)
- Maintains `data/financials/latest.json` pointing to most recent import
- `load_latest()` function available for downstream scripts

### Studios (as of Feb 2026)
| Code | Location          | Status      |
|------|-------------------|-------------|
| BK   | Berkeley          | Active      |
| CC   | Culver City       | Active      |
| CDM  | Corona Del Mar    | Placeholder |
| DN   | Danville          | Active      |
| HO   | Head Office       | Overhead    |
| LF   | Lafayette         | Active      |
| MR   | Marin             | Active      |
| OP   | Ocean Park        | Active      |
| PH   | Presidio Heights  | Active      |
| PS   | Pasadena          | Placeholder |
| RH   | Russian Hill      | Active      |
| SB   | Santa Barbara     | Active      |
| SM   | Santa Monica      | Active      |
| WP   | West Portal       | Placeholder |
| WW   | Westwood          | Active      |

Additional codes in Locations tab without P&L tabs: NS (Not Specified), NP (NAPA), SMR (San Marino)

## GL Code Mapping (Revenue Recognition)
| GL Code | Category                          |
|---------|-----------------------------------|
| 401001  | Machine                           |
| 401002  | Private Pilates                   |
| 401003  | Class Pass                        |
| 401004  | Mighty Teacher Training           |
| 401005  | Livestream Classes                |
| 401006  | Wellhub                           |
| 402000  | Revenue from Old Mighty           |
| 403001  | Machine Breakage                  |
| 403002  | Mighty Teacher Training Breakage  |
| 403003  | Private Pilates Breakage          |
| 403004  | Other Breakage                    |
| 404000  | Retail Sales                      |
| 406000  | Refunds                           |
| 407000  | Discounts                         |

## Email Distribution
- **Sender**: chandler@empirica-analytics.com
- **Test**: chandler.clemons@gmail.com
- **Production**: Rasa Silverman (rasa@crewfinance.com), Cat Martin (cat@mightypilates.com), Vy Nguyen (vy@crewfinance.com), Crew Accounting (accounting@mightypilates.com)

## Key Technical Notes
- Snowflake auth uses RSA key-pair (`config/rsa_key.p8`)
- Visit linking registry prevents overwriting frozen months
- The `IMPUTED/` directory contains reference/override data
- All generated files (outputs/, data/) are gitignored — only code is committed
- Revenue recognition SQL is the core logic (~81KB); changes there affect all downstream outputs

## Conventions
- Currency: commas + 2 decimal places ($1,234,567.89)
- Month references: "YYYY-MM" for CLI args, "Month YYYY" in display
- Studio codes are always uppercase 2-3 letter abbreviations
- Python dependencies: openpyxl, pandas, snowflake-connector-python
