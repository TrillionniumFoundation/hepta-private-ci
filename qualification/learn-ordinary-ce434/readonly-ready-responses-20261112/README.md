# Original T/S Ready-only first reads and production entry audit

Source commit: `57ffff832355d75937045f240fed2c2d48783029`.
Source tree: `f2b297cf94da0029c02e26b644694f7653fa12d7`.
Parent: `f4e008f6ce1162239f0a02f4ce89b8c8185abc36`.
Branch: `codex/learn-readonly-ready-responses-ce434-20261112-v4`.

## What this source changes

Two original readonly connection types can now obtain their first signed T or S from the already admitted original peer, before their future result is known to the consumer. T requires actual D; S requires actual D and T. The first exchange uses the existing fixed readonly purpose, request 1, original initial binding, peer/pidfd and lifetime. It validates the full returned response and windows, then transfers the same connection into the existing evidence reader at request 2. The pre-existing full-pin bind path remains at request 1. Errors consume the original connection. Later reads still perform actual original-owner exchanges and compare the entire signed receipt; the saved pin is not a CURRENT substitute.

No role key, new enrollment, UID, permission, dependency or all-role custody container was created. Missing/Pending initial replies remain errors and cannot manufacture a NoUpdate result. Actual writer files, witness and signing keys remain with the original role owner.

CALLERS adds 14 readonly boundaries and 8 protected files, with exact existing caller-set updates. The fixed source contains 530 unique boundary/inventory IDs, 386 protected records and 315 unique protected paths. All authority flags remain false. The added source module has 6 methods; source inventory increases by 6 from the parent. Counts describe manifest structure; they are not a full caller-proof pass.

Two existing Rust mechanism files were adapted. One tests first Ready-only T response and a second actual exchange on the same stream, and explicitly exercises an unready bootstrap through the new first-read path. The deep original T/S/C mechanism now obtains its actual first T and S before constructing the consuming owner. Its source expects 23 T and 7 S responses; no runtime counts are claimed here. Neither mechanism is ordinary A/B/C acceptance.

## Scoped source QA and its exact qualification limit

`new-readonly-source-v1.log` preserves the failed first run: five mutation subtest failures. The mutation helper targeted the first textual occurrence instead of the required ordered occurrence, and a broad CommitUncertain marker could match a later branch. The helper was corrected to mutate the exact ordered occurrence and the branch check was strengthened to protect the semicolon-terminated return. The raw failure was retained byte for byte, including unittest's trailing space before its first failed subtest. Raw logs are excluded only from the documentation whitespace check.

`new-readonly-source-v2.log` records 16/16 passing source tests: all 6 new methods and 10 affected existing exact-caller methods. Unittest elapsed time is 51.558 seconds; driver time is 52.043972411999675 seconds. Raw log: 3841 bytes, SHA256 `0fe2c9c48e186c54691e3f59b62b8296dab03bb7a2745bd6f792ddced8297010`.

After that pass, only the inventory list's TOML presentation was restored to its prior single-line style to reduce unrelated diff. Parsed TOML equality was checked. Therefore the 16-test result is a scoped working-change validation with an explicit semantics-preserving presentation difference; it is not a byte-pinned test run of published commit 57ffff. Final integrated fixed-source QA, caller proof, formatting and native `just test` remain Root responsibilities. No Rust compiler, cargo, H execution or native test was run by this agent.

All 16 published blobs were fetched back through GitHub and matched the complete local UTF-8 contents and blob IDs; the API tree equals the local committed source tree. The source manifest records each path, size, SHA256 and Git blob.

## Fixed-source production entry audit

Unlike the earlier scoped QA, `production-entry-audit-v1.json` is pinned to the published 57ffff commit and tree. The checkout was clean before and after. The audit indexed all 6699 Git-tracked Rust files across `apps`, `bazel`, `codex-rs`, `qualification` and `tools`, broader than the manifest's registered product source root. The aggregate path/content index SHA256 is `51b7f910ccce9fc2ef9e7866b329d42c47404869ebbebfcc95326c7a869dc8eb`.

It uses the repository verifier's comment/string masking, cfg(test) removal and typed receiver caller discovery. Product-path exclusions are exactly `/tests/`, `/examples/`, and `_tests.rs`. The unchanged executing driver is included. Scope is 12 selected construction/recovery/readonly boundaries, not all 530 boundaries. All 12 matched their explicit caller sets in 144.94535006999922 seconds.

| Boundary family | Product caller result in this source |
| --- | --- |
| Original Training bootstrap create/recover | Empty |
| Original Candidate stage create/recover | Empty |
| Original NoUpdate stage create/recover | Only `cell_q24_candidate_stage_inputs.rs` |
| Retained version host create/recover | Empty |
| S/C original readonly consuming hosts | Empty |
| New T/S first actual readonly response | Empty |

Definitions are in `codex-rs/hepta-agentd/src/cell_q24_training_bootstrap.rs`, `cell_q24_candidate_stage_owners.rs`, `cell_q24_no_update_stage_owners.rs`, `circuit_retained_version_host.rs`, `circuit_selection_readback_host.rs`, `circuit_next_use_readback_host.rs`, and the two changed command-readback files. Exact symbols and discovered caller paths are in the audit JSON. The internal Candidate-to-NoUpdate delegation does not establish an ordinary task entrance.

This is concrete evidence of an unfilled repository production assembly edge. Existing factories and mechanisms do not provide the independent original deployment custody launcher. No verified repository-external launcher has been supplied. This audit does not prove absence outside the repository.

## Read-only H reconciliation

At Root's request, one 45-second read was attempted for `/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/artifact-c2dcb-format-v1/result.json`, and one existing-search list request was made to locate Root's exact deployment-name query. Both remained unknown at 45 seconds. `h-readonly-reconciliation-v1.json` records that boundary. No execution was reissued, no search was started, and no other shared-credential task was treated as this task. Formatter completion and the external launcher remain unconfirmed.

## Acceptance ledger

Positive ordinary adoption: 0. Correct ordinary NoUpdate/fallback: 0. Distinct-input fresh-session C consumption: 0. Actual daemon/Root cold restart: 0. Persistent multi-window learning benefit: not started.

The next required integration is the original independent deployment's verified custody and ordinary task call point: original custody -> actual Ready-only predecessor response -> original consuming owner. The published source is the first-read adapter and source closure needed by that integration, not the integration itself.
