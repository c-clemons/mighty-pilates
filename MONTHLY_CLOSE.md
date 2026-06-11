# Mighty Pilates — Monthly Revenue Recognition Close Procedure

**Owner:** Chandler Clemons (Empirica Analytics) · **Cadence:** Monthly, on or shortly after the 1st of the following month · **Last updated:** 2026-06-11

This document is the canonical procedure for the monthly revenue recognition close. It pairs with the engineering pipeline in `/Users/chandlerclemons/mighty-pilates`. The goal is a repeatable, auditable close that produces:

1. **GL Export workbook** (`Mighty_GL_<Month><Year>_<stamp>.xlsx`) — per-studio + consolidated GL totals
2. **Saasant JE workbook** (`Saasant_Upload_<Mon>_<Year>_<stamp>.xlsx`) — QuickBooks-ready journal entries
3. **Monthly Close Report** (`Mighty_Close_Report_<Mon><Year>_<stamp>.pdf`) — prior-month vs close-month comparison (recognized revenue + cash sales) and sale-month revenue-recognition waterfall

All three are emailed to the Crew Finance + Mighty accounting distro after a test-send to the CFO.

---

## TL;DR — happy-path command

```bash
# Sanity-check first; never run --production without doing this:
python run.py monthly --month YYYY-MM            # default: test email only (chandler.clemons@gmail.com)

# After reviewing the test email and the three workbooks, send to client distro:
python run.py monthly --month YYYY-MM --production --skip-close   # reuse the close, just re-send
```

`--skip-close` re-uses the already-frozen GL so production sends bit-exact files to the test send. **Always pass `--skip-close` on the production send** once you've validated the test.

---

## Step-by-Step Procedure

### Step 0 — Prerequisites (verify before starting)

- Cat (Mighty) has sent her MAY summary (MindBody + ClassPass + Wellhub sales by studio). This is the reconciliation anchor.
- All source feeds in Snowflake are fully landed for the close month (last day of close month is ≤ `MAX(SALE_DATE)` in `PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS` and `MAX(START_DATE)` in `PLAYLIST_DATAMART.CLASSPASS_REPORTING_ANALYTICS.RESERVATIONS`).
- The prior month is **frozen** in `VISIT_LINKING_REGISTRY` (`FROZEN_THROUGH_DATE` includes prior month-end). If not, run `python run.py freeze --month YYYY-MM` for the prior month first — see "Recovering an unfrozen prior month" below.

### Step 1 — Reconcile our sales vs. Cat's figures

```bash
# Quick reconciliation script (template in scripts/may2026_sales_reconcile.py)
# Copy and update the CLIENT dict with Cat's MB + CP totals per studio.
python scripts/<month>_sales_reconcile.py
```

**Expected tolerance:** consolidated totals within 0.5% of Cat's figures (MindBody and ClassPass each). If wider, investigate before proceeding:

- MindBody delta usually comes from refunds posted between Cat's pull date and ours, or differences in fee/account-topup inclusion
- ClassPass delta usually comes from late-arriving reservations syncing into our feed

If we cannot close the gap within tolerance, hard-code Cat's figures into a patch script (`scripts/patch_<month>_sales.py`) following the `patch_cat_revised_sales.py` template.

### Step 2 — Run the close

```bash
python run.py monthly --month YYYY-MM    # default = test mode
```

This invokes:

1. **`close_month()`** — runs the full `revenue_recognition.sql`, freezes the close-month visit assignments to `VISIT_LINKING_REGISTRY`, and re-runs the model with the frozen state
2. **`generate_prior_month_gl()`** — produces the GL Export Excel
3. **`generate_prior_month_saasant()`** — produces the Saasant JE Excel; also writes the GL totals to `FROZEN_MONTHLY_GL` so future re-runs are bit-exact
4. **`generate(close_year, close_month)`** (close report) — produces the Monthly Close Report Excel
5. **`send_reports(mode="test")`** — emails all three to `chandler.clemons@gmail.com`

### Step 3 — Validate the test email

Open the three files. Confirm:

| Check | Where |
|---|---|
| Total Net Sales ≈ Cat's MindBody total (within 0.5%) | GL Export → All Studios tab → `TOTAL_NET_SALES` |
| Class Pass ≈ Cat's CP total | GL Export → `401003 Class Pass` |
| MoM trend isn't anomalous | Close Report → MoM Comparison page |
| Waterfall total = GL Total | Close Report → Waterfall page → TOTAL row vs. GL All Studios sum of earned + breakage + CP |
| Sale-month vintage looks reasonable | Close Report → Waterfall — typically M0 + M-1 dominate (~75%); large M-6+ usually indicates 6-mo-old expirations breaking |
| Saasant JE balances | Saasant Upload → `Deferred Revenue` plug row per studio brings each studio block to zero |
| Per-studio anomalies have known drivers | Close Report → MoM Comparison → "By Studio" — any studio with ±15% MoM should be explainable |

### Step 4 — Production send

After validation, send to the client distribution:

```bash
python run.py monthly --month YYYY-MM --production --skip-close
```

`--skip-close` ensures we re-export the already-frozen month (bit-exact) and don't accidentally re-freeze.

Production distribution list (hard-coded in `pipeline/distribute.py`):
- Rasa Silverman (rasa@crewfinance.com) — Crew Finance lead
- Cat Martin (cat@mightypilates.com) — Mighty CFO
- Vy Nguyen (vy@crewfinance.com) — Crew accountant
- accounting@mightypilates.com — Mighty accounting
- chandler@empirica-analytics.com — sender CC

### Step 5 — Document the close

In a CLOSE_NOTES_<MONTH>.md or in a project memory file, record:

- Date of close
- Reconciliation deltas (our MB+CP vs Cat's, by studio if material)
- Any patches applied (e.g., hard-coded category mappings, recognition-rule fixes)
- Any anomalies surfaced and their explanations
- Any backlog items deferred (e.g., negative deferred balances, dual-path MTT)

---

## CLI Reference

| Command | Purpose |
|---|---|
| `python run.py test` | Verify Snowflake connection |
| `python run.py model` | Run revenue recognition SQL only (no freeze) |
| `python run.py freeze --month YYYY-MM` | Freeze visit-to-package assignments for the month |
| `python run.py close-month --month YYYY-MM` | Run model + freeze + re-run model (no exports, no email) |
| `python run.py export` | Generate prior-month GL + Saasant exports (no email) |
| `python run.py export --ytd` | Generate YTD GL export |
| `python run.py close-report --month YYYY-MM` | Generate the Monthly Close Report only |
| `python run.py send` | Generate exports and email (test mode default) |
| `python run.py send --production` | Same, send to production distro |
| `python run.py monthly --month YYYY-MM` | **Full close: model + freeze + export + close-report + email (test)** |
| `python run.py monthly --month YYYY-MM --production` | Same, production email |
| `python run.py monthly --month YYYY-MM --skip-close` | Re-export and re-email without re-running the close |
| `python run.py monthly --month YYYY-MM --production --skip-close` | Production send after a validated test |

---

## Email Mode Safety

`pipeline/distribute.py` enforces test-by-default. The production recipient list is hard-coded in `PRODUCTION_RECIPIENTS` and only fires when `mode="production"` is explicitly passed. There is no way to accidentally send to production by editing the YAML config — you have to pass the flag on the CLI.

---

## Recovering an Unfrozen Prior Month

If you run a close and the registry shows the prior month was never frozen:

```bash
python run.py freeze --month YYYY-MM    # freezes the orphan month
python run.py close-month --month YYYY-MM   # re-runs the model with the now-frozen prior month
```

Then proceed with the current month's close as normal. Note that any GL we previously emailed for the orphan month may now differ slightly from the regenerated version — flag in the close memo and decide whether to restate.

---

## Recovering from a Bad Close

If you discover a categorization bug or missing recognition rule **after** the close email was sent:

1. Fix the SQL / bucket mapping in `sql/revenue_recognition.sql` or `pipeline/gl_export.py` (and `pipeline/saasant_export.py`)
2. Re-run `python run.py close-month --month YYYY-MM` — this regenerates the model with the fixed logic
3. Re-export: `python run.py export`
4. Compare the new GL against the previously-sent one (preserved in `FROZEN_MONTHLY_GL` table for prior months — query directly)
5. If the delta is material, email Crew a restatement memo with the corrected JEs
6. If the delta is immaterial (<0.5% of monthly revenue), note in next month's close memo and absorb the catch-up in the current month

---

## Source-of-truth Tables (Snowflake)

All in `MIGHTY_PILATES_ANALYTICS.EARNED_REVENUE_ANALYTICS`:

| Table | Role |
|---|---|
| `DAILY_REVENUE_AND_SALES_DETAIL` | Final output — JE source |
| `VISIT_LINKING_REGISTRY` | Frozen visit→package assignments; protects closed months from drift |
| `PACKAGE_EXPIRATION_REGISTRY` | Frozen package expiration dates; drives breakage timing |
| `FROZEN_MONTHLY_GL` | Bit-exact GL snapshots for closed months |
| `PRICING_PER_VISIT_UNIQ` | Package master with deduplicated pricing |
| `REVENUE_CATEGORY_RECOGNITION_TYPE` | Maps each `REVENUE_CATEGORY` to a recognition path (visits-based, immediate, daily-pro-rata, separate) |
| `CATEGORY_COMPATIBILITY_MAPPING` | Cross-category visit linkability matrix |

Source feeds (in `PLAYLIST_DATAMART`):
- `MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS` — MindBody sales detail
- `MINDBODY_REPORTING_ANALYTICS.MART_VISITS` — MindBody visit detail
- `CLASSPASS_REPORTING_ANALYTICS.RESERVATIONS` — ClassPass reservations + rates

---

## Known Issues / Backlog

See task list in project. Current open items as of 2026-06-11:

- **Negative deferred revenue balances** (-$353K across 6 studio × service-type slices). Indicates over-recognition in unlimited/livestream daily-pro-rata or a deferred-rollforward computation bug. Does NOT affect the GL JE (which sums NET_EARNED + NET_BREAKAGE directly, not the balance). To investigate before Q3.
- **Dual-path MTT recognition** (capacity-1 packages route to Schedule path; capacity-N packages route to Usage path). Mechanically correct but worth deciding whether all MTT should be schedule-based.
- **Future-shifting risk on un-snapshotted pricing.** A back-posted MindBody correction to a package's UNIT_PRICE would shift historical recognized revenue. Consider adding `PACKAGE_PRICING_REGISTRY` snapshot.

---

## Change Log

- 2026-06-11 — Initial procedure document. Added `--test`/`--production` mode flag, monthly close report module, and waterfall + MoM analytics. First close: May 2026.
