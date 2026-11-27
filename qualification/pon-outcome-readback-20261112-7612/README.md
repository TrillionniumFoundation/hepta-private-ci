# Native PoN / learning outcome readback evidence

The runtime source is `93fc43f6e87c4514485adcb01a7ffec8ad3b632f`, tree `1de575fdbba23d25c483f539a15b455c9e8859cb`, on #6006 base `3c8dabe46598599e91b2b8b80081e09069ff9426`. The evidence commit changes only this directory; it does not replace the tested runtime identity.

## Changes and observations

The existing local-selection tests now export the original initial checkpoint, Selection checkpoint, committed native use, and terminal checkpoint. The phases are `local_defer_cold`, `local_retain_cold`, and `local_adopt`. Defer and Retain each retain a qualified candidate and the parent model; neither is relabeled as a training or evaluation `NoUpdate`. The retained fixture manifests now match the coordinator's complete shared bundle contract. The existing readback/checkpoint/completion wrapper schemas are unchanged; the initial native bytes use a separate `HEPTA_LEARNING_INITIAL_V1` fixture marker.

Initial receipt-free checkpoints use HEPLCP02. Local-decision Selection and terminal checkpoints use HEPLCP04 with tag 9. These exports do not provide a Root registration or frozen-scope custody proof. Local use has no pending request/output; empty output does not establish an explicit output ACK event. Only the Defer/Retain tests establish cold recovery; `local_adopt` makes no cold-recovery claim.

## Executed gates

* The original `just test --locked --offline -p codex-hepta-agentd --lib ... --no-capture` path ran **7 selected tests: 7 passed, 1035 skipped by the filter**. Source before/after is the same clean runtime source. Complete original stdout is `native.log`, SHA-256 `3e7ee2dcd9019949256a2987a3c8612d976952a58503d7050198adaab11a5261`. Exact commands, environment and tool versions are in `native-preflight.json` and `native-result.json`.
* Scoped `just fmt --base 3c8dabe46598599e91b2b8b80081e09069ff9426`, `just fix -p codex-hepta-agentd --lib --locked --offline`, and final scoped formatting all passed without source drift. Their original logs and stage records are retained.
* A separate unchanged-source target, `q24_actual_trainer_no_update_requires_published_retained_task_and_committed_distinct_input_after_reopen`, passed. It executes source A on actual Q24 model bytes, derives the training batch from the actual output, runs the optimizer to `NoUpdate`, recovers the original published retained task after a lost publication ACK, executes different C input on a reopened model, and cold-reads the original trainer and owner. It retains one FinalUse nonce. Its C output is still pending; this is not a completed delivery/ACK join. Original stdout is `native8.log`, SHA-256 `bf752718b91d313dfd2a626e998f52c95dcb5e41d4a63705a4f63fbf9b1b375e`.
* The seven-target run also includes actual Q24 optimization with unchanged quantized weights, original training-file/witness cold recovery, and the original training-stage Candidate/NoUpdate outcomes. The unchanged-weights unit target checks three optimizer steps and unchanged zero error. These are real bounded optimizer executions with explicit fixture data and credentials.

JUnit files actually retained by these attempts: `[]`. No absent report is reconstructed, and no JUnit-collector gate is claimed. This is scoped native-test evidence, not the full caller, full workspace, UID 0, or daemon/Root acceptance gate.

## Limits and retained failures

The first cloud attempt was run on a dirty preliminary patch above #6006 before the final code source was frozen. It exited **101**, with **zero Rust tests executed**, because offline Cargo lacked `Inflector v0.11.4`. Its original 737-byte log and command/result record are retained. It is not relabeled as an execution of the final runtime source.

The qualified-candidate evaluation and role signatures in the local-choice fixtures remain synthetic. The small Q24 runs establish bounded training/control/owner mechanics; they do not establish an independently measured model benefit. All exports retain `DENY_ALL`, `NOT_EXPORTED`, fixture-derived pins, and `HOLD_NO_GO`. No mining reward, contribution reward, storage payment, issuer permission, or production CURRENT authority is granted.

The inherited #6006 full-caller locator failure and ordinary product-enrollment/independent B/C gaps remain outside this test-only change. Ordinary production adoption, model quality, a complete daemon/Root restart, and whole-system learning benefit remain unqualified. The separate Chain consumer must independently replay and bind the exact original checkpoints and use bytes; the export alone grants it no authority.

`SHA256SUMS` covers the retained original files and this README. `native-markers.json` preserves original execution paths; the matching marker files are retained under their original basenames. No serialized native payload was reconstructed or relabeled.
