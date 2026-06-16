# Decision Log — Mighty Pilates Revenue Pipeline

Running log of categorization, recognition, and policy decisions.
**Append, don't overwrite.** Cite SQL/code line refs when relevant.

---

## 2026-06-16 — MTT geographic reallocation (session location, not sale location)

**Decision:** Mighty Teacher Training revenue is recognized at the **session location**, not the studio where it was sold. Applied to GL 401004 (MTT earned) and 403002 (MTT breakage).

**Mapping:**

| Destination | Receives MTT from |
|---|---|
| Marin (Bay Area sessions) | Berkeley, Lafayette, Russian Hill, Presidio Heights, Danville |
| Westwood (LA sessions) | Culver City, Santa Monica, Ocean Park |
| Santa Barbara | itself (own sessions) |
| Marin / Westwood | own contributions stay put |

**Reasoning:** Per Cat (2026-06-16): "All LA sales go to Westwood where the sessions take place. All Bay Area sales go to Marin where those sessions take place. We want to recognize revenue where the session takes place, not where the sale occurred."

**Implementation:**
- `pipeline/mtt_remap.py` — `MTT_STUDIO_REMAP` (single source of truth) + `remap_studio_by_bucket()` helper
- `pipeline/saasant_export.py` + `pipeline/gl_export.py` — call `remap_studio_by_bucket()` after BUCKET assignment, on the LIVE path only
- Frozen-read paths (`_generate_saasant_from_frozen`, frozen GL overlay) are **not** modified — they replay closed months exactly as originally posted to QuickBooks

**Effective:** **June 2026 close onward** (next monthly close runs with the remap applied automatically).

**Prior months (Feb/Mar/May 2026):** Reclassed via separate manual JEs sent to Crew Finance 2026-06-16. Files: `outputs/MTT_Reclass_Feb-Mar-May_2026_*.xlsx`. April had $0 MTT, no entry needed. After these JEs post, Feb/Mar/May QuickBooks state = original sale-location Saasant + manual reclass = session-location totals (correct).

**To extend mapping in future** (e.g., new studio opens): add to `MTT_STUDIO_REMAP` in `pipeline/mtt_remap.py`. No other code changes needed.

---

## 2026-06-11 — Private Events recognition

**Decision:** `Private Events` category routes to **GL 401001 Machine**, recognition type **`immediate`** (recognized on sale date).

**Reasoning:** Per Cat (2026-06-11): "For now, this should go to classes. It's a mat class. Right now, all Pilates group classes are categorized as machine." Mighty Mixer / Work Hard Play Hard / Pilates and Sound Bath room rentals are billed once and the event happens around the sale date; no per-visit tracking is meaningful.

**Implementation:**
- `sql/revenue_recognition.sql` line ~270: added `('Private Events', 'immediate')` to `REVENUE_CATEGORY_RECOGNITION_TYPE`
- `pipeline/gl_export.py` SERVICE_TYPE_BUCKETS: `"Private Events": "Machine"`
- `pipeline/saasant_export.py` SERVICE_TYPE_BUCKETS: same

**Impact:** ~$1,700/mo in recent months. Back-applies to closed months ($1,178 Jan, $1,450 Mar) — not restated; absorbed in May.

---

## 2026-06-11 — Explicit SERVICE_TYPE → Machine mappings (Other/Unmapped cleanup)

**Decision:** Map the following service types explicitly to **Machine** instead of letting them fall through `.fillna("401001")`:
- `Staff Class`
- `Other`
- `MMP Member Pop-Up` (hyphen variant — the space variant `MMP Member Pop Up` was already mapped)
- `Student Mighty Monthly Pass` (when appearing as a service_type, typically on breakage events)
- `Mighty Workshop`

**Reasoning:** These were all silently bucketing to Machine via the fillna fallback. Making them explicit (a) eliminates the "Other / Unmapped" row in the monthly close report, (b) prevents future SERVICE_TYPE drift from going unnoticed (any new unmapped type will resurface the row).

**Implementation:** `pipeline/gl_export.py` + `pipeline/saasant_export.py` SERVICE_TYPE_BUCKETS additions. JE dollar amounts unchanged.

---

## 2026-06-11 — Dual-path MTT recognition policy

**Decision:** Keep the existing dual-path recognition for Mighty Teacher Training.

**Mechanic:**
- Capacity-1 MTT packages ("Deposit", "1st Payment - PTT") → cohort **Schedule** path (`MTT_COHORT_CLASS_DATES`)
- Capacity-N MTT packages ("Final Payment - PTT", "Full Single Payment - PTT") → **Usage** path (per actual class attendance)

**Reasoning:** Mechanically correct per the conflicting client directives in commits `97321b5` ("MTT to visits-based") and `7766082` ("MTT schedule-based"). Each individual package routes by capacity. Total recognition per package is accurate.

**Open question (backlog):** Whether all MTT should be schedule-based regardless of capacity. Not blocking; can revisit.

---

## 2026-06-11 — Duration registry policy (>6 month packages)

**Decision:** Maintain current hard-coded duration registry. Only **two** categories of packages get >6 month durations:

1. **Livestream** category — 12 months (category default in `CATEGORY_MONTHS`)
2. **Dynamic Pricing** product override — 12 months (override in `PRODUCT_DURATION_OVERRIDE`)
3. **PACKAGE_EXPIRATION_FORCED 12-month backstop** for packages with no other expiration source

For all other categories, durations are 1 or 6 months. MindBody-stored TRUE expirations (`PACKAGE_EXPIRATION_TRUE`) are honored when they exceed these defaults; only 184 packages have TRUE-source durations >6 months across the entire history.

**Reasoning:** Validated against M-7+ vintage in the May close — 100% of $6,333 in M-7+ traced back to IMPUTED-source packages under these documented rules. No anomalies.

---

## 2026-06-11 — Visit expiration filter (proposed, NOT applied)

**Decision:** Drafted `sql/PROPOSED_visit_expiration_filter.sql` but **did not apply**. Adversarial verification showed the underlying model is internally consistent — no double-recognition occurs because `USAGE_TOTALS` includes all-time visits and breakage = `GREATEST(deferred - all_time_usage, 0)`. The "$22K dropped" the filter would catch is a within-package timing matter, not a magnitude error.

**Real concern remains:** Some HARD-linked post-expiration visits may indicate **linker contamination** — visits possibly should link to a newer (unexpired) package the same client owns. This is an allocation question, not a magnitude one. Filed to backlog as data-quality investigation.

---

## 2026-06-11 — May 2026 prior-period restatement

**Decision:** Do **not** restate Jan-April 2026 JEs in QuickBooks despite the Private Events fix back-applying small amounts to those months.

**Reasoning:** Total impact across Jan-Mar 2026 = $2,628, well below materiality. Crew has booked the JEs already. The fix is absorbed in May's close. May's actual JE is correct.

---

## 2026-06-11 — Email distribution policy

**Decision:** Test mode is the default. Production requires explicit `--production` flag.

**Implementation:**
- `pipeline/distribute.py` defines `PRODUCTION_RECIPIENTS` (hard-coded, cannot be modified via YAML)
- `TEST_RECIPIENTS` = chandler.clemons@gmail.com only
- `PRODUCTION_CC` = chandler.clemons@gmail.com (copy of every client email lands in Chandler's gmail)
- Sender authenticates as `chandler@empirica-analytics.com` (Workspace app password) but display `From` and `Reply-To` are configurable

**Production list (as of 2026-06-11):**
- Cat Martin (cat@mightypilates.com)
- Rasa Silverman (rasa@crewfinance.com)
- Vy Nguyen (vy@crewfinance.com)
- Ashley Palomarez (accounting@mightypilates.com)
