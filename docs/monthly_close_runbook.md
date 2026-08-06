# Mighty Pilates Monthly Close Runbook

The end-to-end sequence for a monthly rev rec close, distilled from the 2026-06 close. Assumes v2 pipeline (Cat-authoritative durations, expiration-aware linking, `PACKAGES_NEEDING_DURATION` hard-fail).

## Preconditions

- Prior month is frozen in `VISIT_LINKING_REGISTRY` (`FROZEN_THROUGH_DATE = <prior month end>`) and in `FROZEN_MONTHLY_GL`.
- Cat's Package Duration Review spreadsheet (`Copy of Mighty_Pilates_Package_Duration_Review.xlsx`) mirrored into `sql/v2/cat_approved_durations.sql`. If Cat has emailed corrections since last month, update the SQL first.
- MindBody / accountant data through the close month is loaded and current in Snowflake.
- Cat's cash sales figures for the close month have been received.

## Sequence

### 1. Ingest close-month cash sales + ClassPass

Cat emails a CSV or spreadsheet with per-studio cash sales (and a ClassPass column) for the close month.

**Reconcile** against MindBody `MART_SALES_DETAILS` (per studio) — copy the reconcile script (`scripts/jul2026_sales_reconcile.py`) each month. Sum `NET_PAYMENTAMT_LOCAL` for the MB-side; it ties to Cat's non-ClassPass figure within ~0.4%. **Do NOT reconcile against `DAILY_REVENUE_AND_SALES_DETAIL`** — that table is the rev-rec model's *output* and is stale for the close month until Step 2 runs. Flag any per-studio mismatch ≥ $1K to Cat before proceeding. (See memory `mighty-pilates-close-data-lags`.)

**ClassPass override (required every close):** the `RESERVATIONS` feed lags ~5 days at close, so ClassPass reads light. Add Cat's authoritative per-studio ClassPass for the close month to `CAT_CLASSPASS` in `pipeline/classpass_actuals.py` (keyed by `MONTH_YM`). `gl_export` and `saasant_export` self-apply it (and `freeze_from_live` inherits it), so 401003 posts Cat's figure, not the lagging feed. Skipping this understates ClassPass, the JE, and the frozen GL.

**Apply** the cash sales to Streamlit dashboard + Excel model:

```bash
python scripts/apply_cat_<mon>_cash_sales.py
```

(Duplicate `apply_cat_jul2026_cash_sales.py` as the template each month.)

### 2. Run v2 rev rec model

Registry updates happen inside this step. `run_model.py` loads Cat's approved durations, executes the SQL up to the split marker, checks `PACKAGES_NEEDING_DURATION`, aborts if anything Cat hasn't ruled on has recent sales, otherwise writes the registry.

```python
from pipeline.connection import get_connection
from pipeline.run_model import run_revenue_model
conn = get_connection()
run_revenue_model(conn, cutoff_date="<YYYY-MM-30>", pipeline_version="v2")
```

**If it aborts**: quantify the flagged products with the close-month deferred query, decide whether each is a naming variant of an already-approved product (auto-add per the duration-procedure memory) or a genuinely new SKU (email Cat for approval). Update `cat_approved_durations.sql` accordingly and re-run.

**If it completes**: proceed. `LEGACY_UNRULED_PRODUCTS` may show a warning count — that's fine for the close, but track for a future Cat audit.

### 3. Multi-angle pre-close audit

Sanity-check before freezing:

- MoM trend by studio (`SUM(EARNED + BREAKAGE)` grouped by `STUDIO_NAME`, month).
- Breakage % — historically 14-24% of total revenue. A big swing needs explanation.
- MTT: current-cohort recognition matches expected schedule dates (see `feedback_mighty_pilates_mtt_recognition`). Confirm gap months land at ~$0.
- ClassPass MoM sanity (from `PLAYLIST_DATAMART.CLASSPASS_REPORTING_ANALYTICS.RESERVATIONS`).
- Frozen-visit invariant: `frozen_visits ⊆ VISITS_LINKED` — no drops.

### 4. Freeze the month

```python
from pipeline.run_model import freeze_month
from pipeline.frozen_gl import freeze_from_live
freeze_month(conn, "<YYYY-MM-30>")               # visit registry
freeze_from_live(conn, <YYYY>, <MM>)              # FROZEN_MONTHLY_GL from Saasant JE
```

### 5. Generate the deliverables

```python
from pipeline.gl_export import generate_gl_export
from pipeline.saasant_export import generate_saasant_export
from pipeline.close_report import generate_close_report  # if used
gl_path = generate_gl_export(conn, "<YYYY-MM-01>", "<YYYY-MM-30>", output_dir="outputs")
sa_path = generate_saasant_export(conn, "<YYYY-MM-01>", "<YYYY-MM-30>", output_dir="outputs")
```

Plus the MTT summary if the month has cohort class dates or Cat wants the standing follow-up:

```bash
python scripts/build_mtt_close_summary.py --month <YYYY-MM>
```

### 6. Reconcile GL vs Saasant BEFORE offering to send

**Every account. To the cent.** GL uses gross-positive; Saasant uses credit-negative for revenue and credit-positive for refunds/discounts. Compare sign-flipped Saasant sums against GL "TOTAL" column and confirm delta < $0.02 per account. Compare format (row count, unique accounts, Deferred Revenue = $0 auto-balancing convention) against prior month.

### 7. Test-send to self

```python
from pipeline.distribute import send_reports
send_reports(files=[gl_path, sa_path, close_report_pdf], subject="...", body="...", mode="test")
```

Test mode sends to `chandler.clemons@gmail.com` only. Review the numbers and text.

### 8. Cat review before the accounting team

**Standing preference (Cat, 2026-08): Cat reviews the close each month before it goes to Crew.** After the self-test looks right, send a review copy to Cat + Chandler using the recipient override, with the email reframed for review (greeting "Hi Cat," + a line that it's for her review ahead of the accounting team). Same attachments and headline/MoM content.

```python
send_reports(
    files=[gl_path, sa_path, close_report_pdf],
    subject="Mighty Pilates — <Month> <Year> Monthly Close (for your review)",
    body="<review-framed body>",
    recipients=["Cat Martin <cat@mightypilates.com>"],
    cc=["chandler.clemons@gmail.com"],
)
```

### 9. Production distribution

After Cat approves **and** Chandler gives explicit sign-off:

```python
send_reports(files=[gl_path, sa_path, close_report_pdf], subject="...", body="...", mode="production")
```

Production hits Cat, Rasa, Vy, Ashley (Cc Chandler). Body **mirrors prior months** — "Hi team," + headline totals + attachments only; the MoM bridge / visit-trend lives in the PDF, not the email body. Cat stays on the production distro by default (she gets a second copy) unless told otherwise.

### 10. MTT follow-up email (separate)

Cat wants the per-cohort MTT summary as a standing follow-up to the standard package. Draft using the same structure as `outputs/MTT_June2026_Summary_for_Cat.xlsx` and the 2026-06 email body. Send to Cat directly (not the full distribution).

### 11. Commit + push

```bash
git add scripts/apply_cat_<mon>_cash_sales.py outputs/ dashboard/data/
git commit -m "<Month> <Year> close: cash sales + rev rec + exports"
git push
```

## Anti-patterns to avoid (learned the hard way 2026-07-08)

- **Never re-date a pack whose current expiration is in a frozen month.** Doubles the breakage across frozen + current.
- **Never overwrite `PACKAGE_EXPIRATION_REGISTRY` from ad-hoc SQL.** Use the pipeline's Section 4D append-only pattern. Snapshot the table before any manual surgery (`PACKAGE_EXPIRATION_REGISTRY_SNAPSHOT_YYYYMMDD CLONE`).
- **Never silently default a duration.** Anything not on Cat's list flags in `PACKAGES_NEEDING_DURATION` and either gets auto-mapped (documented naming variant) or bounces back to Cat for approval.
- **Never subtract NET cash sales from GROSS GL revenue** without labeling both sides. It looks like deferred revenue and misleads Cat.
- **Never ship without GL/Saasant reconciliation.** It only takes 30 seconds and catches format drift.
- **Never make unilateral policy decisions on Cat's behalf.** Naming variants of already-approved products are the one carve-out; everything else surfaces to her.

See `memory/feedback_mighty_pilates_*` for the underlying reasoning on each of these.

## Deferred items on the roadmap

From Fable's 2026-07-08 audit (`reviews/pipeline_review_2026-07-08.md`):

- **F11**: Section 6 HARD sibling-pack ranking + SOFT greedy-capacity accounting edge cases.
- **F12**: Duration off-by-one across sources (TRUE has +1, others don't).
- **F13**: Hygiene — returned-pack netting validation, `NORMALIZE_CATEGORY` case-folding for 'FEES', `run_model.py` cutoff-injection string-replace fragility.
- **LEGACY_UNRULED_PRODUCTS Cat-audit workflow**: 116 products / $2M pre-Cat-list sales. Not blocking any close but eventually needs a Cat pass — bundle into a single email with proposed defaults so she can bulk-approve.
- **F6 stranded pre-2025 MTT deferred (~$372K)**: intentionally deferred; per Chandler no re-adjudication.
