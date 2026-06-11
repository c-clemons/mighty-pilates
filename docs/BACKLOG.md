# Backlog — Mighty Pilates Revenue Pipeline

Items that need attention but aren't blocking any monthly close. Sorted by priority.

---

## P1 — Investigate before Q3 2026

### Negative deferred revenue balance computation

**Symptom:** `DAILY_DEFERRED_REVENUE_BALANCE` shows -$354K aggregate negative at May 31, 2026 across these slices:

| Studio | Service | Balance |
|---|---|---:|
| Westwood | Machine | -$128,132 |
| Santa Monica | Livestream | -$102,159 |
| Presidio Heights | Livestream | -$45,521 |
| Ocean Park | Machine | -$34,422 |
| Presidio Heights | Private | -$26,313 |
| Marin | Private | -$14,580 |
| Lafayette | Unlimited | -$1,451 |
| Presidio Heights | Unlimited | -$1,044 |

**Verified NOT to affect:** the GL JE — that's computed from `NET_EARNED + NET_BREAKAGE` directly on `DAILY_REVENUE_AND_SALES_DETAIL`. Per-package math is internally consistent (TOTAL_NET_USED never exceeds DEFERRED_REVENUE).

**Probable cause:** Bug in `DAILY_DEFERRED_REVENUE_BALANCE` rollup logic (sql/revenue_recognition.sql lines ~2137 onward). Likely a sign error or join condition.

### Linker contamination — past-expiration visit allocation

**Symptom:** 672 May visits ($22,120) linked HARD to packages with `EXPIRATION_DATE` before the visit date. These visits' usage events fire, shifting some recognition from prior-month breakage into current-month usage.

**Verified NOT a quantity bug:** Total recognized per package equals total deferred per package. No double-counting.

**Real question:** Should those May visits have linked to **newer** unexpired packages owned by the same client? If yes, we're misallocating revenue between same-client packages (no total impact). If no, current allocation is correct.

**Diagnostic needed:** For each post-expiration-linked visit, check whether the client has a newer unexpired package the visit could have linked to.

**Reference:** `sql/PROPOSED_visit_expiration_filter.sql` (NOT applied — drafted as proof-of-concept) and `scripts/validate_expiration_filter.py`.

---

## P2 — Process / robustness improvements

### Pricing-per-visit snapshot at freeze

**Risk:** A back-posted MindBody correction to `UNIT_PRICE` on a frozen-period package would shift historical recognized revenue on next re-run. The visit-to-package link is frozen via `VISIT_LINKING_REGISTRY`, but the **dollar value per visit** is read live from `PRICING_PER_VISIT_UNIQ`.

**Fix:** Add `PACKAGE_PRICING_REGISTRY` that snapshots `UNIT_PRICE`, `NET_PACKAGE_PRICE`, `DEFERRED_REVENUE`, `NET_REVENUE_PER_VISIT` at freeze time. The model would read frozen pricing for any package whose first visit is in a frozen month.

### MTT cohort schedule promotion to persistent table

**Risk:** `MTT_COHORT_CLASS_DATES` and `MTT_COHORT_WINDOWS` are TEMP tables rebuilt every model run from hard-coded `VALUES` clauses. An editor changing the VALUES would silently restate all historical MTT recognition.

**Fix:** Promote to a persistent table that's source-controlled and changes require a migration script.

### April-freeze process gap

**Symptom:** April 2026 was not frozen until the start of the May close (mid-month).

**Fix:** Add to `MONTHLY_CLOSE.md` procedure — verify prior month is frozen BEFORE running this month's close. Consider adding an assertion in `cmd_monthly` that errors out if `VISIT_LINKING_REGISTRY.FROZEN_THROUGH_DATE < first-of-this-month - 1`.

---

## P3 — Categorization cleanups

### MTT Unlimited Livestream perk packages

**Issue:** Bundled livestream perk packages for MTT students (`"Unlimited Livestream (PTT students only)"`, `"MTT Unlimited Livestream"`) recognize as `REVENUE_CATEGORY = 'Mighty Teacher Training'` → GL 401004. Arguably should go to GL 401005 Livestream.

**Magnitude:** ~$60/mo. Immaterial. Left as-is per Cat 2026-06-11.

**Fix path:** Product-description override in SQL — `PRODUCT_DESCRIPTION ILIKE '%livestream%'` AND `REVENUE_CATEGORY = 'Mighty Teacher Training'` → remap to Livestream.

### Founding Members MMP — 8-year duration outlier

**Issue:** One package (`160859-100005122-5733789-100019`, Founding Members MMP at Westwood, sold 2024-09-13) has `EXPIRATION_DATE = 2033-01-13` from MindBody TRUE source. Lifetime/founding membership.

**Magnitude:** Tiny ($0 deferred). No GL impact.

**Action:** Sanity-check with Cat that this is intentional and the customer is still active.

---

## P4 — Future-shift / data-quality monitoring

### Run `scripts/validate_expiration_filter.py` each month

Even though the filter isn't applied, the script's output is a useful data-quality signal:
- Total visits past expiration
- Distribution by days-past-expiration
- Distribution by HARD vs SOFT_GLOBAL link type

If the magnitude grows materially or shifts toward longer days-past-expiration, that's a red flag worth chasing.

### Watch for new unmapped SERVICE_TYPEs

The monthly close report drops the "Other / Unmapped" row when empty but resurfaces it when non-zero. Any month where it reappears = a new MindBody service type needs an explicit bucket assignment in `pipeline/gl_export.py` and `pipeline/saasant_export.py`.

---

## Completed (moved here from session notes)

- 2026-06-11: Private Events recognition fixed (→ Machine immediate)
- 2026-06-11: Other/Unmapped silent mappings made explicit (Staff Class, MMP Pop-Up hyphen variant, etc.)
- 2026-06-11: Monthly Close Report PDF infrastructure built
- 2026-06-11: Test/Production email mode safety enforced
- 2026-06-11: Procedure documented in `MONTHLY_CLOSE.md`
