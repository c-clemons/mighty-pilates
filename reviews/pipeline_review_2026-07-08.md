# Mighty Pilates Revenue Recognition Pipeline — Deep Review
**Date:** 2026-07-08
**Scope:** `sql/v2/revenue_recognition_v2.sql` (v2, June close), `sql/revenue_recognition.sql` / `sql/v1/revenue_recognition_v1_FROZEN.sql` (v1), `pipeline/*.py`, `sql/v2/cat_approved_durations.sql`, live Snowflake state of `PACKAGE_EXPIRATION_REGISTRY`, `VISIT_LINKING_REGISTRY`, `FROZEN_MONTHLY_GL`.
**Method:** full read of the MindBody data dictionary (2026-07 update), line-level review of v1/v2 SQL and Python orchestration, session-transcript reconstruction of today's registry operations, and read-only Snowflake diagnostics to verify actual table state (all query results below are from the live warehouse as of this afternoon).

---

## Summary (most severe first)

1. **CRITICAL — The 2026-07-08 ad hoc registry rebuild reintroduced the exact double-count structure the MB refresh was backed out for, plus a silent 6-month default.** The live `PACKAGE_EXPIRATION_REGISTRY` now contains only two sources, both assigned today: `CLIENT_APPROVED` (178,738) and `IMPUTED_FALLBACK_6MO` (34,783). All TRUE/MB provenance was destroyed, every legacy pack was re-dated, and 717 pre-2026 packs with **$70,954** of unused residual now expire June 2026+ — v1 already booked (much of) that breakage in months posted to QBO.
2. **CRITICAL — $254,045 of June 2026 deferred (1,126 packs, ~12 products) silently got a 6-month default** (`ELSE DATEADD(MONTH, 6, ...)` in the rebuild) because their names don't exactly match Cat's list — new June promos ("Align & Shine Sale", "The Final Stretch Sale", "Summer Solstice Sale") and renamed New Client Specials ("valid for 30 days"). The New Client Special variants should be 1 month per Cat; they got 6. This is a direct violation of the locked policy, in the close that is shipping.
3. **CRITICAL — For new packages, the v2 SQL's priority order (TRUE 0 → MB_ACTUAL 1 → CLIENT_APPROVED 2 → MB_DERIVED 3) puts MindBody above Cat**, contradicting the locked policy ("Cat's rules govern regardless of what MindBody's `PRICING_OPTION_EXPIRATION_DATE` says"). Every pack sold after today's rebuild gets MB dates whenever MB has any — including the 68 known Cat-vs-MB mismatch products.
4. **HIGH — `cat_approved_durations.sql` is not wired into the pipeline.** The v2 SQL's "CLIENT_APPROVED" source reads the stale ~70-entry `PRODUCT_DURATION_OVERRIDE` list, not Cat's 204-product table. Two divergent definitions of "client approved" now coexist: legacy registry rows (Cat exact-match via today's ad hoc rebuild) vs. new rows (old override list, only after MB is silent).
5. **HIGH — The strict-policy guard is checking the wrong condition and can never fire in practice.** `PACKAGES_NEEDING_DURATION` flags products with *no signal from any of four sources*; since MB_ACTUAL covers ~81% of sale lines and MB_DERIVED soaks up most of the rest, it currently holds 7 stale products with **zero** trailing-3-month sales — the `run_model.py` hard-fail has never triggered and won't. It should flag "not on Cat's list," which today would have caught all 12 silent-default June products.

---

## Findings by section

### F1. Registry rebuild (2026-07-08) — double-count risk reintroduced, provenance destroyed
- **File/lines:** ad hoc heredoc executed in session (transcript line ~3071); resulting state in Snowflake `PACKAGE_EXPIRATION_REGISTRY`; interacts with `sql/v2/revenue_recognition_v2.sql` §4D and `pipeline/frozen_gl.py`.
- **What's wrong:** The rebuild replaced the entire registry:
  `CASE WHEN cad matches THEN Cat's duration ELSE DATEADD(MONTH, 6, SALE_DATE) END`, `START_DATE = SALE_DATE` for everything, `ASSIGNED_ON = 2026-07-08`, sources `CLIENT_APPROVED` / `IMPUTED_FALLBACK_6MO` only. This:
  - Re-dated legacy packs whose old expirations already fired breakage in closed months. The Step 3.5 comment in the v2 SQL (lines 1036–1059) explains precisely why this is unsafe for the MB refresh — the Cat rebuild has the identical structure, just with different replacement dates.
  - Destroyed `TRUE` activation-based windows (memberships activated after sale date now start at sale date) and all source provenance, making any future "what did v1 book and when" reconstruction impossible from the registry itself.
- **Concrete scenario:** A 10-pack sold Dec 2025; v1 imputed Machine = 1 month → expired Jan 2026, breakage booked in a month already posted to QBO. Cat says 6 months → new expiration Jun 2026: v2 books breakage **again** in June. Measured exposure: **717 packs, $70,954 residual** (pre-2026 sales, current expiration ≥ 2026-06-01, residual > 0).
- **Suggested fix:**
  1. Quantify per-month: for the 717 packs, reconstruct v1's booked breakage month (v1 logic is deterministic: `PRODUCT_DURATION_OVERRIDE` → `CATEGORY_MONTHS` → 6mo default; `sql/v1/revenue_recognition_v1_FROZEN.sql` lines 745–777 preserve it for exactly this) and net the double-booked dollars out of June+ expirations, e.g. a one-time `BREAKAGE_ALREADY_BOOKED` exclusion table keyed by PACKAGE_ID that `expiration_events_agg` anti-joins.
  2. Snapshot the registry (`CREATE TABLE PACKAGE_EXPIRATION_REGISTRY_20260708 CLONE ...`) before any further surgery, and add a `PRIOR_EXPIRATION_DATE` column on future re-dates so the original date is never lost again.
- **Severity: critical**

### F2. Silent 6-month fallback — 34,783 packs, $254K of June deferred
- **File/lines:** same ad hoc rebuild (`ELSE DATEADD(MONTH, 6, ...)`, `EXPIRATION_SOURCE = 'IMPUTED_FALLBACK_6MO'`).
- **What's wrong:** Locked policy: "Any product not on her list must be flagged and surfaced, never silently defaulted." 34,783 packs are on the silent default. For June 2026 sales alone: **1,126 packs, $254,045 deferred**, concentrated in:

  | Product | Packs | Deferred | Note |
  |---|---|---|---|
  | Align & Shine Sale - 8 classes for $295 (SF Marin) | 408 | $119,981 | new June promo, not on Cat's list |
  | Align & Shine Sale - 8 classes for $280 (East Bay) | 319 | $88,424 | ditto |
  | New Client Special … (valid for **30 days**) variants | ~341 | ~$33,300 | Cat's list has the "1 month" wording = **1 month**; these got **6** |
  | The Final Stretch Sale / Summer Solstice Sale | 43 | $11,471 | new June promos |

- **Concrete scenario:** "New Client Special: 5 for $99 (valid for 30 days)" — contractually a 1-month pack — now defers breakage until Dec 2026 instead of Jul 2026: July revenue understated, December overstated. The Align & Shine promos are plausibly 6 months (prior flash sales were), but that is Cat's call, not a default. Note none of the June promos say "Flash Sale", so even the `%Flash Sale%` catch-all in `PRODUCT_DURATION_OVERRIDE` misses them.
- **Suggested fix:** Take the 12 product names to Cat today (they map almost one-to-one onto existing patterns on her list); add them to `cat_approved_durations.sql`; re-date only `IMPUTED_FALLBACK_6MO` rows; make the rebuild's ELSE branch an **error path** (row goes to `PACKAGES_NEEDING_DURATION`, not the registry). Also: the match is `TRIM()`-only and case-sensitive — normalize case and collapse internal double spaces before comparing, or variants like Cat's own "Mighty Monthly  20 Pass" row will keep missing.
- **Severity: critical**

### F3. New-package priority order puts MindBody above Cat
- **File/lines:** `sql/v2/revenue_recognition_v2.sql` §4D Step 2, lines 966–1024; also §4B lines 811–818 (`PACKAGE_EXPIRATION_CLIENT_APPROVED` excludes any pack that has a TRUE or MB_ACTUAL row).
- **What's wrong:** For packages not yet in the registry (i.e., every sale from tomorrow on), CLIENT_APPROVED is only consulted when both TRUE and MB_ACTUAL are absent. MB_ACTUAL is populated on ~81% of lines, so Cat's durations effectively never apply to new sales — exactly the failure mode documented in `outputs/Cat_vs_MindBody_Duration_Comparison.xlsx` (Machine +60d, Workshop 365d vs 30d, etc.).
- **Concrete scenario:** July 2026 sale of "10 Machine Classes": Cat = 6 months; MB gives ~8 months. The registry locks the MB date (registry rows are never recalculated), so even wiring Cat's list in later won't fix it without another risky rebuild.
- **Suggested fix:** Reorder to `CLIENT_APPROVED (0) → flag (no fallback)`. Per the memory doc, TRUE and MB_ACTUAL should be demoted to *diagnostic* comparisons (operational-gap detection), not registry sources. If a data-driven safety net is wanted for products Cat hasn't ruled on, that is what `PACKAGES_NEEDING_DURATION` + hard fail is for.
- **Severity: critical**

### F4. Cat's durations table is orphaned; PRODUCT_DURATION_OVERRIDE is the live "client" source
- **File/lines:** `sql/v2/cat_approved_durations.sql` (referenced by nothing in the repo — verified by grep); `sql/v2/revenue_recognition_v2.sql` §4B-SHARED lines 635–719.
- **What's wrong:** The pipeline's CLIENT_APPROVED table joins `PRODUCT_DURATION_OVERRIDE` (LIKE patterns, ~70 entries, "client-approved as of 2026-04-08" + 3 v2 additions). Cat's July spreadsheet (204 products, including the 2026-07-08 MMP-20 correction) exists only as a standalone file that today's ad hoc rebuild happened to load. The next `run.py model` uses the old list for new packs. Divergences already exist — most notably `PRODUCT_DURATION_OVERRIDE` line 709 still has **'Mighty Monthly 20 Pass' = 1 day**, while Cat's corrected value (and the memory doc's example) is **1 month**; "8 Machine Classes" (Cat: 1 month) is absent from the override list entirely.
- **Suggested fix:** Make `cat_approved_durations.sql` the single source: execute it as part of the model run (inline in the SQL or run first in `run_model.py`), rewrite `PACKAGE_EXPIRATION_CLIENT_APPROVED` to join `CAT_APPROVED_DURATIONS` on a normalized exact name, and delete the duplicated per-product entries from `PRODUCT_DURATION_OVERRIDE` (keep it only for pattern-style rules like `%Flash Sale%` if Cat wants them — and document that it is subordinate to the exact list).
- **Severity: high** (critical in combination with F3)

### F5. `PACKAGES_NEEDING_DURATION` + hard-fail guard test the wrong condition and never fire
- **File/lines:** `sql/v2/revenue_recognition_v2.sql` §4C lines 918–947; `pipeline/run_model.py` lines 78–100.
- **What's wrong (verified live):** The table currently holds 7 products / 31 packs, **0** with sales in the trailing 3 months — the guard has never aborted anything. Four compounding reasons:
  1. It only flags products with no signal from **any** of TRUE / MB_ACTUAL / CLIENT_APPROVED / MB_DERIVED. Policy requires flagging products **not on Cat's list**; MB signals should not suppress the flag.
  2. MB_DERIVED exists specifically to absorb what MB_ACTUAL misses, guaranteeing near-zero flags.
  3. The guard runs *after* §4D has already inserted new packs into the persistent registry with MB-based dates. Even when it aborts, wrong durations are already locked in (registry rows are never recalculated), so a later Cat correction won't take effect — a one-way ratchet.
  4. The trailing-3-month filter in `run_model.py` can skip a product that still carries live deferred balances.
- **Suggested fix:** Redefine the diagnostic as `packs where CAT_APPROVED_DURATIONS has no match` (keep the MTT/Fees carve-outs); run the check (and abort) **before** §4D writes the registry; replace the 3-month filter with "any pack with non-zero remaining deferred."
- **Severity: high**

### F6. $372K of MTT deferred is stranded outside all cohort windows
- **File/lines:** `sql/v2/revenue_recognition_v2.sql` §4B-MTT lines 772–779 (`MTT_COHORT_WINDOWS` earliest purchase 2025-01-01), `mtt_purchase_cohort` inner join lines 2246–2248.
- **What's wrong (verified live):** 350 MTT packs with `SALE_DATE < 2025-01-01` and positive deferred (**$372,321**) match no cohort window. They are excluded from breakage (§9 `expiration_events_agg` excludes MTT) and get no `mtt_schedule_events` rows → their residual never recognizes and never breaks; deferred is permanently overstated.
- **Concrete scenario:** A PTT payment sold Nov 2024. If pre-acquisition ("old Mighty", pre-2024-12-13) liabilities intentionally stay off the new entity's P&L, document that and exclude them explicitly via `IS_OLD_MIGHTY` — but purchases between 2024-12-13 and 2024-12-31 are new-entity and are also stranded by the 2025-01-01 floor.
- **Suggested fix:** Extend `Catchup 2025`'s `EARLIEST_PURCHASE_DATE` to 2024-12-13 and add an explicit `IS_OLD_MIGHTY = 1` exclusion for the remainder; add a validation that MTT deferred outside all windows = 0. Same issue recurs at the far end: purchases after the last defined window (2027-03-22) will strand silently — add a "purchase after last cohort window" check too.
- **Severity: high**

### F7. `IS_IMPUTED` CASE has no ELSE — 34,783 rows fall through to NULL
- **File/lines:** `sql/v2/revenue_recognition_v2.sql` §4D Step 5 lines 1114–1129.
- **What's wrong (verified live):** `PACKAGE_EXPIRATION.IS_IMPUTED` is NULL for every `IMPUTED_FALLBACK_6MO` row (the label isn't in the CASE). Anything that segments by IS_IMPUTED (ledger `MAX(IS_IMPUTED)`, close-audit queries) silently ignores exactly the rows most in need of scrutiny.
- **Suggested fix:** Add an `ELSE` branch — or better, carry `EXPIRATION_SOURCE` through to `PACKAGE_EXPIRATION` as a string and stop collapsing provenance into an int.
- **Severity: medium**

### F8. Frozen-visit guarantee leaks: 377 registry visits dropped from `VISITS_LINKED`
- **File/lines:** `sql/v2/revenue_recognition_v2.sql` §6 `capped` CTE lines 1512–1558 (inner join to `ep_raw` requiring `PO_CAPACITY_COUNT > 0 AND PACKAGE_TYPE <> 'Unlimited'`), plus `WHERE pkg_visit_rank <= PO_CAPACITY_COUNT` (line 1558).
- **What's wrong (verified live):** Of 672,127 frozen visits, **377** are missing from final `VISITS_LINKED`: 366 because the package no longer exists in `PRICING_PER_VISIT_UNIQ` (source-data drift / dedupe changes), 7 zero/NULL capacity, 4 capacity-exceeded. 0 were reassigned (good). Dropped frozen visits mean closed-month usage recomputes differently from what was booked — small dollars today, but it breaks the "frozen = immutable" invariant and will grow as MindBody restates history.
- **Suggested fix:** In `capped`, LEFT JOIN `ep_raw` and let frozen rows bypass both the join and the capacity cap (`WHERE pkg_visit_rank <= PO_CAPACITY_COUNT OR is_frozen`). Add a post-run validation: frozen visits not present in `VISITS_LINKED` = 0.
- **Severity: medium** (structural; dollars currently small)

### F9. "No restatement" has no anchor for Jan–Apr 2026, and live already diverges from frozen May/June
- **File/lines:** `pipeline/frozen_gl.py`; `pipeline/gl_export.py` lines 291–304; `pipeline/saasant_export.py` lines 130–136; live `FROZEN_MONTHLY_GL`.
- **What's wrong (verified live):** `FROZEN_MONTHLY_GL` contains only 2026-05 and 2026-06. Jan–Apr QBO entries came from v1 runs whose inputs (the registry) were destroyed today; any re-export of those months now produces different numbers with no warning. Current live breakage: Jan 134,290 / Feb 141,621 / Mar 123,992 / Apr 131,322 — with nothing to reconcile against. May live (132,361) vs frozen (141,175) differs by **−$8,814**, June by −$892, confirming the model no longer reproduces what was posted. Dashboards or deep-dives reading live tables for closed months will disagree with QBO.
- **Suggested fix:** Backfill `FROZEN_MONTHLY_GL` for Jan–Apr from the Saasant JE files actually sent to Crew (`freeze_from_saasant_file` already supports exactly this). Add a standing close-audit check comparing live month totals vs frozen for all frozen months so drift is visible instead of silent.
- **Severity: high**

### F10. June close froze before today's fixes
- **What's wrong (verified live):** `VISIT_LINKING_REGISTRY` has 14,184 visits frozen through 2026-06-30 and June GL is frozen at 138,824 breakage — but the Section 6 fix, the MMP-20 correction, and the registry rebuild all landed afterward. The shipped June JE embeds pre-fix numbers (breakage delta ~−$892 vs the current model, plus whatever earned-revenue timing shifted).
- **Suggested fix:** Decide explicitly: re-freeze June (`freeze-gl --force` + re-send the JE) or accept and note the delta in the close memo. Don't leave it implicit.
- **Severity: medium**

### F11. HARD linking + Section 6 fix edge cases
- **File/lines:** §6 `bp_ranked` lines 1255–1264 (one HARD candidate per `UNIQUE_TRANSACTION_ID`, chosen by capacity, `rn_bp = 1` at line 1289), `hard` expiration join line 1296, `soft_scored`/`soft_assigned` lines 1446–1476.
- **What's wrong:**
  1. HARD only ever considers the highest-capacity package per payment ref. With the new expiration join, a visit outside that pack's window but inside a *sibling* pack's window (same payment ref, multi-line sale) can't HARD-link; it falls to SOFT, which requires `GLOBAL_CLIENT_KEY` and a category-compatibility match — if the sibling's category isn't in `CATEGORY_COMPATIBILITY_MAPPING`, the visit goes unmatched and the pack's dollars later become breakage.
  2. SOFT capacity assignment is greedy and mis-counts: `package_visit_sequence` (line 1475) numbers **candidate** visits per package, not accepted ones. A visit whose preferred pack has `capacity` earlier candidates is excluded from that pack even when those earlier candidates were ultimately assigned elsewhere — the visit can end up unmatched despite room existing.
  3. Multiple candidate active packs: SOFT's ranking (`match_priority → same-studio → earliest EXPIRATION_DATE → sale_gap`) consumes the earliest-expiring compatible pack first — correct FIFO behavior; no change needed.
  4. Frozen assignments: preserved (0 reassigned) except the F8 drops.
- **Suggested fix:** (1) In `hard`, admit all packs under the payment ref whose window covers the visit; rank window-satisfying first, capacity second. (2) Replace the greedy sequence with an iterative assignment, or accept it and monitor `DIAGNOSTIC_UNMATCHED_VISITS_OPEN` month-over-month for growth.
- **Severity: medium**

### F12. Duration off-by-one inconsistency across sources
- **File/lines:** `PACKAGE_EXPIRATION_TRUE` line 542 (`DATEDIFF + 1`) vs MB_ACTUAL line 572 and CLIENT_APPROVED lines 802–806 (no `+1`); the ad hoc rebuild also used no `+1`.
- **What's wrong:** `PACKAGE_DURATION_DAYS` is inclusive for TRUE rows and exclusive elsewhere; it feeds the daily pro-rata denominators (`LIVESTREAM_DAILY`, `UNLIMITED_DAILY`), so identical packages amortize at slightly different daily rates depending on source, and cross-source duration comparisons (like the Cat-vs-MB workbook) are systematically off by one day.
- **Suggested fix:** Pick one convention (recommend `DATEDIFF(DAY, start, exp)` with inclusive `BETWEEN start AND exp` linking) and apply everywhere.
- **Severity: low**

### F13. Minor / hygiene
- **Returned packs may keep full sale value:** the base filter keeps `IS_RETURN_OR_RETURNED = 1` Pricing Option rows (line 423) so returns net out, but `PRICING_PER_VISIT_UNIQ` dedup (line 495) *prefers the non-return row* per PACKAGE_ID — a sale+return pair that collapses to one PACKAGE_ID keeps the positive sale. Add a validation: net sales of fully-returned packs ≈ 0. Consider also `MART_VISITS.IS_RETURNED` to drop visits paid by returned POs.
- **`NORMALIZE_CATEGORY` doesn't fold `'FEES'` into `'Fees'`**, so the diagnostic's `NOT IN (…'Fees')` misses upper-case variants (fails safe — they'd surface — but noisy).
- **Packs with no `PACKAGE_EXPIRATION` row silently park deferred forever** (`hard` inner join drops their visits; `expiration_events_agg` never fires). Today only unlimited/deposit packs are in that state (excluded anyway), but under the F5 "flag, don't write" fix, unresolved packs will be there by design — add a "deferred with no expiration row" audit line.
- **`run_model.py` cutoff injection** string-replaces the first `WHERE v.CLASS_DATE IS NOT NULL` — correct today, fragile forever. Put an explicit `$MODEL_CUTOFF_DATE` placeholder in the SQL.

---

## Explicit answers to the six numbered questions

**1. Is the back-out clean? Residual pollution in `PACKAGE_EXPIRATION_REGISTRY`?**
The back-out of the *MB refresh itself* is clean: Step 3.5 is an empty stub and zero registry rows carry `Refreshed IMPUTED->MB_ACTUAL` notes (verified live). But the registry is **not** clean, because the subsequent "rebuild from Cat's spreadsheet" replaced every row: all 213,521 rows have `ASSIGNED_ON = 2026-07-08`, sources only `CLIENT_APPROVED` (178,738) / `IMPUTED_FALLBACK_6MO` (34,783). Three artifacts remain: (a) the silent 6-month fallback rows (F2); (b) wholesale re-dating of legacy packs — the same double-count mechanism as the refresh, measured at 717 packs / $70,954 of residual now set to re-fire breakage in June+ after v1 booked it in already-posted months (F1); (c) total loss of provenance and of v1's original dates (also of TRUE activation-based start dates), so the double-count can only be reconstructed by re-running v1's deterministic duration logic from `sql/v1/`.

**2. Does v2 faithfully replicate v1's duration logic where Cat is silent, and correctly override where she's present?**
No, on both counts, and differently per codepath:
- *Legacy packs (in registry):* Cat's exact matches apply (good), but where Cat is silent the ad hoc rebuild used a flat 6 months — not v1's `PRODUCT_DURATION_OVERRIDE → CATEGORY_MONTHS → 6mo` chain. Every Cat-silent Machine pack (v1: 1 month) is now 6 months; every Cat-silent Livestream (v1: 12 months) is now 6.
- *New packs (post-rebuild sales):* the v2 SQL uses TRUE → MB_ACTUAL → the stale override list → MB_DERIVED. Cat's spreadsheet isn't consulted at all (F4), and MB outranks the client list anyway (F3). So neither v1 fidelity nor Cat compliance holds going forward. (The earlier "v1 reconstruction" bug — CATEGORY_MONTHS without the override — is at least recoverable: v1's real logic is preserved in the FROZEN file; use that file, not memory, for any future reconstruction.)

**3. Does the Section 6 fix have edge cases? Multiple packs? SOFT ranking? Frozen preservation?**
The fix is directionally right and applied consistently (HARD line 1296, HARD_CROSS_STUDIO line 1344, SOFT line 1431 all require the visit inside the pack window). Edge cases: (a) HARD considers only the highest-capacity pack per payment ref, so a window-failing visit with an in-window sibling pack under the same payment ref detours through SOFT and can go unmatched if category-incompatible (F11.1); (b) SOFT's greedy `package_visit_sequence` counts candidates rather than assignments and can strand visits (F11.2); (c) with multiple active candidate packs, SOFT consumes the earliest-expiring compatible same-studio pack first — the right FIFO choice; (d) frozen assignments survive except **377 dropped** by the capacity-cap inner join, 366 of them because the package vanished from `PRICING_PER_VISIT_UNIQ` (F8); 0 frozen visits were reassigned. One more interaction: because the registry was re-dated to Cat's often-shorter windows, pre-2026 historical visits *not* in `VISIT_LINKING_REGISTRY` re-link under the new windows, which is part of why live Jan–May no longer matches what was booked (F9).

**4. Other MindBody columns that could help with the Cat-vs-MB systematic differences?**
Yes — as *diagnostics and validators*, never duration sources (per the locked policy):
- **`MART_VISITS.SALE_ID` (net-new)** — a direct visit→sale link. The most valuable new column: it can validate (and in v3, largely replace) the PAYMENT_REF_NO + client-key + category-compatibility linking heuristics. Pair with **`NUM_DEDUCTED`** — the pipeline currently assumes every visit deducts exactly 1 session, which multi-deduct visits violate.
- **`MART_VISITS.PRICING_OPTION_EXPIRATION_DATE`** — MB's expiration of the PO that actually paid each visit; ideal for measuring how often clients genuinely use packs past Cat's contractual window (the operational-gap report for Cat).
- **`VISITS_REMAINING_ON_PRICING_OPTION`** — counts scheduled future visits as used; a *current-state* snapshot, so it cannot drive historical rec, but at month-end it's a strong reasonableness check on imminent breakage (packs about to expire per Cat that still show many remaining visits are her "extend or enforce" candidates).
- **`IS_PRICING_OPTION_ACTIVE`** — also current-state only; use as an operational-gap detector (active in MB but expired per Cat = front desk will still accept the pack), not as a rec input.
- **`MART_VISITS.IS_RETURNED`** — exclude visits paid by returned POs from usage.
- **`MART_MEMBERSHIP_DAILY_DETAILS.LAST_REMAINING_VISIT_DATE`** — a fully-consumed pack should show ~zero breakage at Cat's expiration; good validation join.
- For MTT specifically, no sales-side column resolves the payment-schedule vs training-window ambiguity; the cohort-schedule model already in place is the right answer.

**5. Is `PACKAGES_NEEDING_DURATION` triggering as designed? Does the hard-fail guard catch what it should?**
It triggers as *implemented* but not as *intended*. Verified: 7 products / 31 packs, none with trailing-3-month sales → the guard has never fired and structurally almost cannot (MB_ACTUAL + MB_DERIVED absorb everything). Meanwhile the 12 June products that actually needed flagging sailed through and took a silent 6-month default. The MTT/Fees exclusions are fine; the defect is that the check tests "no signal from any source" where policy requires "no Cat rule," and it runs after the registry insert so even a triggered abort leaves wrong durations permanently locked in. See F5.

**6. Should `PACKAGE_EXPIRATION_MB_DERIVED` be removed?**
Yes — remove it as a registry source. Under "Cat's durations are the only source," a trailing-12-month median of MB expirations is definitionally a MindBody fallback, however well-guardrailed; worse, its existence is what neuters the diagnostic (Q5). The n≥5 / IQR≤0.30 machinery is genuinely useful — repurpose it as a *suggestion generator* in the close audit ("new product X: MB-derived duration ≈ 180d, propose to Cat"), feeding the flag report instead of the registry. Same verdict, more strongly, for MB_ACTUAL as a registry source (F3): keep the table, use it only for the Cat-vs-MB gap report.

---

## Things done well

- **The registry concept is right:** write-once expiration assignments with provenance, never recalculating history, is the correct architecture for a no-restatement close; likewise the two-phase close (freeze visits → re-run → freeze GL) in `run_model.py` is clean and idempotent (already-frozen guards on both paths).
- **Frozen GL replay** (`frozen_gl.py`: bit-exact Saasant reproduction, explicit sign conventions, parse-back from the actual JE file) is a robust pattern, and `mtt_remap.py`'s docstring explaining why frozen months deliberately don't re-apply the remap is exemplary documentation.
- **The Section 6 expiration-aware linking fix is correct and consistently applied** across all three link paths, with the 2026-06-01 boundary preserving v1 behavior for history — the immutability comment block at `visits_linked_clean` is exactly the kind of reasoning capture this pipeline needs more of.
- **Backing out the refresh was the right call**, and the Step 3.5 tombstone comment (mechanism + rejected alternatives) preserves the reasoning where the next person will find it.
- **MTT cohort-schedule recognition** (visits first, residual spread over class dates, no breakage) is a defensible, client-aligned method and materially better than duration-based rec for that product.

---

## Recommended next actions, prioritized

1. **Stop the bleeding on the registry (today/tomorrow).** Clone the current registry as a snapshot; take the 12 `IMPUTED_FALLBACK_6MO` product names to Cat (the two "Align & Shine Sale" SKUs alone are $208K of the $254K, and the "30 days" New Client Specials are near-certainly 1 month); re-date only fallback rows; change every write path so a non-match goes to the flag table, never to a default.
2. **Fix the priority order and wire in Cat's list before the next model run.** `CAT_APPROVED_DURATIONS` becomes the sole duration source for new packs (normalized exact match); TRUE / MB_ACTUAL demoted to diagnostics; MB_DERIVED deleted as a source; hard-fail check moved before the §4D registry insert; retire the per-product rows of `PRODUCT_DURATION_OVERRIDE` (fix or remove the stale 'Mighty Monthly 20 Pass' = 1 day entry either way).
3. **Resolve the $71K double-count before July close.** Reconstruct v1's booked-breakage months for the 717 re-dated packs using the frozen v1 SQL's deterministic logic; suppress or manually reverse the June+ re-fires for dollars already posted; document pack-level decisions in the close memo.
4. **Backfill `FROZEN_MONTHLY_GL` for Jan–Apr 2026** from the JE files actually sent to Crew, and add a standing live-vs-frozen drift check for all frozen months. Decide explicitly whether June gets re-frozen after today's fixes (current breakage delta ~−$892).
5. **Close the frozen-visit leak** (F8): LEFT JOIN + frozen bypass in the `capped` CTE, plus a "frozen ⊆ VISITS_LINKED" validation (currently 377 short).
6. **Decide the stranded MTT deferred** ($372,321 pre-2025): explicit old-Mighty exclusion and/or catch-up window extension to 2024-12-13; add "MTT deferred outside all cohort windows = 0" and "purchase after last cohort window" checks.
7. **Quality pass (lower urgency):** `IS_IMPUTED` ELSE branch or source-string passthrough (F7); duration off-by-one normalization (F12); HARD sibling-pack ranking and SOFT greedy-capacity monitoring (F11); returned-pack netting validation and `MART_VISITS.IS_RETURNED` (F13); adopt `MART_VISITS.SALE_ID` + `NUM_DEDUCTED` as a validation layer now, with an eye to making SALE_ID the primary link in v3.
