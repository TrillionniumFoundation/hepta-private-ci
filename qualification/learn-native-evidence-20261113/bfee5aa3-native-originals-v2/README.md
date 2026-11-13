# Bfee A-v2 originals and read-only DATA observations

Exact native source: bfee5aa363cb63897c28c8f74fd6b167de5e859b, tree d24d13a0d716036319a6b814dd89b8e913689b00. The complete 15,497-file physical source hash was unchanged before and after execution. Earlier failed source-preflight and successful hydration/compile attempts remain in the parent evidence history.

## Actual outcomes

| Gate | Actual outcome |
| --- | --- |
| Seven-package scoped fix v2 | Exit 0, unchanged source, 114.677388904 seconds; no tests executed |
| Publisher binding | 6 passed, 0 failed, 0 skipped; exact roster |
| Circuit source-lease budget reducer | 2 passed, 0 failed, 0 skipped; exact roster |
| Root filesystem | 2 passed, 0 failed, 0 skipped; exact roster |
| Ordinary A | 0 passed, 1 failed, 0 skipped; test duration 4.881 seconds |
| Whole Adopt / evaluated post-B NoUpdate / cold | 0 / 0 / 0 |

A failed with `ordinary original Objective returned conflict or uncertain ACK; no inferred execution`. This error groups two outcomes and does not identify the precise returned variant. The driver preserved both child exits and cleanup. No successful ACK, timeout cause, A completion, independent Outcome, B evaluation or whole-chain completion is inferred from a durable prefix.

## Actual archived DATA

The read-only collector exited 0 and retained 261 regular originals (8,972,543 input bytes) in `originals.tar.xz`. All 20 version-pinned download chunks, the 317,900-byte archive SHA-256, the embedded manifest and every member were checked. Collection did not rerun the tests or open business owners.

Two diagnostics examined this same archive. SQLite was read using private copies of DB, WAL and SHM, with `mode=ro` and `query_only`. Original archive and copied durable DB/WAL bytes remained unchanged; private SHM cache changes are explicitly recorded. No original database was checkpointed or modified.

* Circuit `ordinary-original-a` had its original 120,000 ms limit. First Advance occurred 2,908 ms after created_at; computation_claimed followed 6 ms later. Revision was 2, its sole activation was in_flight, stop_reason was null, and no Complete/terminal event existed in this archived prefix.
* RunStart framing contained one complete v2 `Compiled` record and no Conflict record. This is structural DATA, without new native authentication or a delivered-ACK claim.
* Source framing showed request and input claim/complete pairs, with no result or withdrawal stage.
* Cell framing contained one HPTACJ04 tag-3 admission, snapshot revision 0, model generation 1. No tag-4 queue-age or tag-0 commit frame existed in these bytes. Only named prefix fields and chain checks were decoded; no native Cell receipt or authority was reconstructed.
* The actual `circuit_learning_outbox_v1` query for this run returned zero rows. Absence of an outbox row alone does not establish that execution never began.

The full scripts, exact SQL, source-codec hashes, raw collection/observer receipts, output reports, initial local launcher failure before any diagnostic child start, and successful successor execution are preserved in `diagnostics-and-receipts.tar.xz`. Private SQLite copies are not duplicated because the original DB/WAL/SHM are already archived. None of these observations replays business activity or upgrades a pending stage to Completed.

The same appendix preserves Root's byte-verified draft PR #6284 receipt, pointing to remote 3a26e6e9baba163c31d395e69e114af6a5c97efb, and the static review of prepared-only next compile templates. This evidence task did not create/update the PR, change source refs, upload the prepared template or execute Rust. The original v1 template and the separately named metadata-only v2 refinement are retained.

`native-manifest.json` is the exact collector manifest. `support-manifest.json` lists every supporting member and complete SHA-256. `verification.json` ties the independent outcomes to their exact original result hashes. Parent evidence is retained unchanged.
