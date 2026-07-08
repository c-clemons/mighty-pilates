# v1 Pipeline — FROZEN

These files are the frozen state of the revenue recognition pipeline as of the last month closed under v1 logic (May 2026 close, distributed to Cat/Rasa/Vy/Ashley).

**Do not modify these files.** They are preserved for:
- Reference during v2 refactor
- Delta-comparison audit when v2 is first run
- Rollback path if v2 introduces regressions

Corresponding live files in `sql/`:
- `revenue_recognition_v1_FROZEN.sql` ← `sql/revenue_recognition.sql`
- `hard_coded_medians_v1_FROZEN.sql` ← `sql/hard_coded_medians.sql`
- `visit_linking_registry_v1_FROZEN.sql` ← `sql/visit_linking_registry.sql`

The v2 pipeline lives in `sql/v2/`. When v2 is confirmed correct (May delta ≤ tolerance and June close successful), we can retire v1 — but not before.
