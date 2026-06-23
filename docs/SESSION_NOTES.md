# Session Notes — Mighty Pilates Revenue Pipeline

This file is the running log of significant work sessions on the pipeline.
**Append, don't overwrite.** Newest at the top.

---

## 2026-06-23 — May 2026 actuals integration + Stage 2 formalization

**Owner:** Chandler Clemons · **Client trigger:** Cat sent the May 2026 accountant package (`Mighty Pilates_Financials_053126.xlsx`).

### Outcomes

1. **May 2026 actuals are live** in committed_actuals.json, the Streamlit dashboard, and the Excel financial model.
2. **Stage 2 (dashboard update) formalized** as a CLI command (`python run.py update-dashboard --month YYYY-MM`). Prior months had been done via ad-hoc patch scripts; this is now repeatable.
3. **MTT geographic reclass propagated to Feb/Mar/May**. The new accountant package reflects Crew's posting of the reclass JE we sent 2026-06-16, so per-studio MTT now shows:
   - Marin: Feb $34,358 / Mar $960 / May $17,745
   - Westwood: Feb $29,483 / Mar $7,173 / May $22,654
   - Santa Barbara: Feb $10,056 / Mar $7,183 / May $0
   - All other studios: $0 MTT for these months
4. **Excel financial model refreshed** via `refresh_from_streamlit.py` in the `financial-modeling` repo. Trailing-3-month averages recomputed. Last actuals month bumped to May 2026.
5. **Excel snapshot committed** to `snapshots/excel/Mighty_Pilates_Financial_Model_May2026.xlsx` for version control.

### Code changes (this session)

- **New: `pipeline/dashboard_update.py`** — Stage 2 module. Handles:
  - Subtotal label injection (`401000 Sessions`, `403000 Breakage Revenue` only — empirically calibrated against the May 26 actuals_snapshot to match the dashboard's existing convention)
  - Per-studio refund/discount sign flip (negative QBO → positive dashboard)
  - Per-month diff output highlighting MTT reclass + Crew restatement changes
  - Audit-trail snapshot to `data/financials/streamlit_snapshots/`
- **New: `dashboard/data/latest.json`** — sibling pointer file written every update.
- **Updated: `run.py`** — new `update-dashboard` subcommand wiring.
- **Updated: `MONTHLY_CLOSE.md`** — added Actuals Integration section (Stages 1-4).
- **Updated: `docs/SESSION_NOTES.md`** — this entry.

### Diff observations worth flagging

- Feb 2026: MTT reclass moved ~$73K between studios, cascading through Total Income / NOI / Net Income at each affected studio (net-zero at consolidated)
- Mar 2026: Same pattern, smaller magnitude (~$15K)
- Apr 2026 minor: WW had a $11K reclass of 602002 1099 Compensation → 0 (likely Crew correcting a misposting); RH Mar had a $2.3K Office Supplies reclassification; few other small ones
- All consolidated PL totals tie to the new May 2026 file as expected

### State at session end

- `dashboard/data/committed_actuals.json` last_actuals_month = "May 2026"
- `dashboard/data/latest.json` exists, points to May 2026
- `snapshots/excel/Mighty_Pilates_Financial_Model_May2026.xlsx` tracked in git
- All changes committed and pushed to `origin/main`

### Late-session update: Cat's authoritative May cash sales applied

Cat sent her May 2026 cash sales totals per studio (image, total = $799,443) and asked us to make the Excel and dashboard match.

Applied via `scripts/apply_cat_may2026_cash_sales.py`:
- `client_sales_forecast[STUDIO]['2026-05']` set to Cat's per-studio values
- `client_sales_forecast_consolidated['2026-05']` = $799,443
- `monthly_sales['2026-05']` = $799,443
- Excel `Sales Forecast` tab rows 6-17 column H (May 2026): per-studio values
- Excel `Cash Flow Forecast` tab cell H7: replaced stale hardcoded $918,006.51 with formula `='Sales Forecast'!H18` so it auto-syncs to the studio-sum (consistent with adjacent months which use the same formula)
- Excel saved to THREE locations: original Desktop path, new `~/Desktop/Mighty Pilates/` location (Cat's preferred working directory), and the repo snapshot
- Header text on Sales Forecast tab updated: "Jan-May 2026 actuals (locked, Cat-authoritative)..."

Rounding note: Sum of Cat's per-studio values = $799,442 (off by $1 from her reported total of $799,443). Excel SUM formula computes $799,442; dashboard consolidated explicitly set to $799,443. Immaterial.

### Procedure for June 2026 (and every month going forward)

Once Crew sends the June financial package:
1. `python run.py import-financials "<June file>"`
2. `python run.py update-dashboard --month 2026-06`
3. `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 /Users/chandlerclemons/financial-modeling/models/mighty/refresh_from_streamlit.py`
4. Copy the Excel into `snapshots/excel/Mighty_Pilates_Financial_Model_Jun2026.xlsx`
5. `git add snapshots/excel/...xlsx && git commit && git push`

See `MONTHLY_CLOSE.md` § Actuals Integration for the full procedure including validation steps.

---

## 2026-06-16 — MTT geographic reallocation policy + working capital options

**Owner:** Chandler Clemons · **Client touch:** Cat Martin

### Outcomes

1. **Manual reclass JE sent to Crew** for Feb / Mar / May 2026, reclassifying posted MTT revenue from the sale studio to the session-location studio per Cat's policy:
   - Marin (Bay Area sessions) ← Berkeley, Lafayette, Russian Hill, Presidio Heights, Danville
   - Westwood (LA sessions) ← Culver City, Santa Monica, Ocean Park
   - Santa Barbara stays
   - April had $0 MTT — no entry needed
   - File: `outputs/MTT_Reclass_Feb-Mar-May_2026_20260616_104421.xlsx` (one Saasant-format JE per month, each net-zero)
2. **Baked the geographic policy into the standard monthly Saasant + GL exports** going forward (June 2026+). The live-path `BUCKET == MTT` rows have their STUDIO_NAME remapped before JE construction. Frozen-read path is unchanged so prior closed months replay exactly as posted to QuickBooks at the time.
3. **Working capital options for Mighty** discussed (no PG, 18-month entity). Conclusion: traditional bank LOC unlikely without PG. Best fit = revenue-based financing (Pipe, Capchase, Clearco, Wayflyer) + processor-attached (Stripe Capital, MindBody partner). Email draft prepared for Cat with links.

### Code changes (this session)

- **New: `pipeline/mtt_remap.py`** — `MTT_STUDIO_REMAP` dict, `remap_studio_by_bucket()` helper. Single source of truth for the policy.
- **New: `scripts/mtt_reclass_2026.py`** — one-off generator that reads QBO P&L by Location exports and produces the Saasant-format reclass JEs for Feb/Mar/May (the manual catch-up).
- **Updated: `pipeline/saasant_export.py` + `pipeline/gl_export.py`** — apply `remap_studio_by_bucket()` after BUCKET assignment on the live path. Frozen-read path untouched.
- **Updated: `docs/DECISIONS.md`** — new entry for the policy.

### Decisions captured

- **MTT revenue follows session location** (Cat directive 2026-06-16). Applied via `MTT_STUDIO_REMAP` in `pipeline/mtt_remap.py`. Remap is on live path only — frozen replays of closed months are unchanged.
- **No restatement of Feb-May beyond the manual JE.** QuickBooks for those months = original sale-location Saasant + the reclass JE we sent today = correct session-location totals.

### State at session end

- Cat has the reclass file in her inbox.
- June 2026 not yet closed (will be the first month auto-remapped).
- Production email pipeline is functional (May test → production cycle confirmed).
- All code committed and pushed to `origin/main`.

---

## 2026-06-11 — May 2026 close + monthly procedure infrastructure

**Owner:** Chandler Clemons (Empirica Analytics) · **Client:** Cat Martin (Mighty Pilates)

### Outcomes

1. **May 2026 close completed and sent to production** (Crew Finance + Mighty accounting).
   - Files: `Mighty_GL_May2026_20260611_111133.xlsx`, `Saasant_Upload_May_2026_20260611_111134.xlsx`, `Mighty_Close_Report_May2026_20260611_111136.pdf`
   - Reconciled within 0.16% of Cat's MB+CP figures.
   - April was also frozen mid-close (it had been left unfrozen since the April close).
2. **Built repeatable monthly close procedure** documented in `MONTHLY_CLOSE.md`.
3. **Added the Monthly Close Report PDF** (`reports/monthly_close_report.py`) — MoM comparison + revenue recognition waterfall (sale-month vintage M0..M-7+).
4. **Test/Production email modes** (`pipeline/distribute.py`) — `--production` flag explicit, no way to accidentally send to client.
5. **Categorization fixes** to eliminate silent fallbacks in the GL JE:
   - `Private Events` → recognition type `immediate`, GL 401001 Machine (per Cat — mat-class event rentals)
   - `Staff Class`, `Other`, `MMP Member Pop-Up` (hyphen variant), `Student Mighty Monthly Pass` (as service_type), `Mighty Workshop` → explicit `Machine` mappings (previously silently fell through `.fillna("401001")`)

### Decisions captured (also in `docs/DECISIONS.md`)

- **Private Events route to GL 401001 Machine** (Cat directive 2026-06-11). Mat-class event rentals. Recognition type = `immediate`.
- **Dual-path MTT recognition is acceptable for now.** Capacity-1 packages (deposit, 1st payment) recognize via cohort Schedule path; capacity-N packages (final payment, full payment) recognize via Usage. Confirmed mechanically correct.
- **MTT Unlimited Livestream perk packages** ($59 in May) currently book to MTT (401004) via REVENUE_CATEGORY. Cat-approved to leave as-is; tagged as future cleanup if value grows.
- **6-month vs 12-month duration policy stays as-is**: only Livestream category and Dynamic Pricing product override are >6mo (12mo). MTT/PIC are 6mo schedule-based (no breakage).
- **No restatement of Jan-April 2026** despite the Private Events fix back-applying small amounts to those months ($1,178 Jan, $1,450 Mar). Immaterial; absorbed in May.
- **Pre-close audit identified, deferred to backlog**: negative deferred revenue balances (-$354K aggregate across 8 studio×service slices), visit-linker contamination causing past-expiration usage events.

### Investigations conducted

| Investigation | Finding |
|---|---|
| Total reconciliation vs Cat MB+CP figures | ✅ Within 0.16% at consolidated level |
| Q1 2026 cleanup carryover into May | ✅ $67K from 2025 sales, 82% Machine (Nov 2025 expirations hitting 6-mo mark) — expected |
| MTT cohorts driving $12,979 in May | ✅ 100% Summer 2026 cohort (6 class dates in May); enumerated by studio |
| Presidio/Russian Hill MTT "underrecognition" | ✅ Not a bug — capacity-1 deposit packages route to Schedule; capacity-N final-payment packages route to Usage |
| $59 MTT Unlimited at Culver City | ✅ Not a bug — bundled livestream perk for PTT students; correctly classified |
| Pre-close multi-angle audit (SQL logic, data integrity, future-shift risks) | Surfaced negative deferred balances + linker contamination + Other/Unmapped service types; most other agent findings were false positives (e.g., "ClassPass excluded from UNION" — that's by design, exports pull CP directly) |
| M-7+ vintage in close report waterfall ($6,333) | 100% IMPUTED-source packages, all under documented duration rules (Private 6mo, Machine class pack 6mo, Livestream 12mo, Dynamic Pricing 12mo override) |
| Past-expiration visits driving M-7+ etc. | Filter would shift $22K of usage backwards into prior-month breakage; net total recognition unchanged. **Not a double-recognition bug** — `USAGE_TOTALS` correctly includes all-time visits and breakage is `GREATEST(deferred - usage, 0)`. The user wants the linker contamination question revisited later as a data-quality matter. |

### Code changes (committed in 3 logical commits this session)

- `sql/revenue_recognition.sql` — added `('Private Events', 'immediate')` to `REVENUE_CATEGORY_RECOGNITION_TYPE`
- `pipeline/gl_export.py` + `pipeline/saasant_export.py` — explicit SERVICE_TYPE → bucket mappings (Private Events, Staff Class, Other, MMP Pop-Up, SMMP, Mighty Workshop → Machine)
- `pipeline/distribute.py` — `mode='test'`/`mode='production'`, hard-coded `PRODUCTION_RECIPIENTS`, CC support, `from_display` + `reply_to` headers
- `run.py` — `close-report` subcommand, `--production`/`--skip-close` on `monthly`, headline-totals email body composition
- `reports/monthly_close_report.py` — new PDF report module with `pull_mom`, `pull_waterfall`, `generate`, `get_headline_totals`, `compose_email_body`
- `MONTHLY_CLOSE.md` — full close procedure documentation
- `sql/PROPOSED_visit_expiration_filter.sql` — proposed (NOT applied) patch for visit-expiration filter
- `scripts/may2026_sales_reconcile.py` — Cat-figures reconciliation script (template for monthly use)
- `scripts/validate_expiration_filter.py` — diagnostic for visits past package expiration
- `config/snowflake_config.yaml` (NOT in git per .gitignore) — added `from_display`, `reply_to`

### Open items at session end

See `docs/BACKLOG.md`. Highest priority for future investigation:

1. **Visit-linker contamination** — for each post-expiration visit linked HARD to an expired package, is there a newer unexpired package the same client owns? (Not a magnitude problem; an allocation problem.)
2. **Negative deferred revenue balance computation** — the rollup table goes -$354K negative when underlying package math is consistent. Bug is in the balance computation logic (lines ~2137+ of `revenue_recognition.sql`), not in the JE.
3. **Pricing-per-visit snapshot at freeze** — back-posted MindBody corrections to `UNIT_PRICE` would shift historical recognized revenue. Add `PACKAGE_PRICING_REGISTRY` snapshot at freeze time.

### State at session end

- Snowflake `EARNED_REVENUE_ANALYTICS.VISIT_LINKING_REGISTRY` frozen through 2026-05-31
- Snowflake `EARNED_REVENUE_ANALYTICS.FROZEN_MONTHLY_GL` populated with May 2026 (104 GL rows)
- May 2026 production email sent at 2026-06-11
- Ready for June 2026 close (commands documented in `MONTHLY_CLOSE.md`)
