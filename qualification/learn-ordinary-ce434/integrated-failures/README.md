# Original integrated qualification failures

This pack preserves original host file bytes returned by complete, versioned reads. `manifest.json` records their original absolute paths, byte lengths, SHA256 digests, source identities and qualification boundaries. The normalized process-observation JSON files are clearly separate from original file bytes.

## v5: actual formatter child 83af1c661b85

The original process authoritatively failed with exit 1 and complete, durable terminal publication. Source closure executed 195 tests: 193 passed and two failed. Parser, full caller proof and native tests were not reached. The exact original format patch and actual formatter commit log are retained. Later source repairs do not change this result.

## v6: fixed source 1bcbcb7d4327

All 195 source checks and 16 parser controls passed. Actual helpers built and verified. The native command failed before test execution with E0507 in the Material valid-renewal negative test; zero native tests ran and no countable JUnit exists. The complete original native execution record and 45,137-byte raw log are retained. The two-line test fix is separately committed as `a3a73c740fb0cb83b2afad0fadf958161f2394ad`; no pass is inferred for it.

The v6 preparation result and outer-process observation are intermediate snapshots: the full caller proof was still running when read. They are not a terminal success or a completed full-proof claim. Later observations must be retained separately rather than replacing these bytes.

The later terminal observation is now retained separately in `1bcbcb7d4327-compile-failure/terminal-observation.json`, explicitly labeled as normalized `h_process_status` JSON. The original outer job `1a1cc7949e6-2564-f4a` finished **failed, exit 1**, with complete and durable output and confirmed terminal publication; it was not timed out, cancelled or automatically retried.

`final-preparation-result.json` preserves the original 3,037-byte final host result, distinct from the earlier preparation snapshot. The original full caller proof finished **exit 1 after 1,491.8085601557977 seconds**. Its complete 219-byte `caller-proof-full.log` reports:

```text
FAIL_HEPTA_CALLER_PROOF: learning_original_evaluation_receipt_readback: codex-rs/hepta-agentd/src/circuit_model_qualification_test_support.rs: unresolved possible OriginalCellEvaluationReceiptOwnerV1::readback receiver
```

The native command still has compile exit 101 and **zero executed native tests**. The final preparation record's `rust_executed` flag indicates that the native command was invoked; it does not establish test execution or success. The retained intermediate files have not been replaced or reinterpreted, and later source repairs cannot change either original failure.

## v7: fixed source 14065b700e16

Original process `1a1ccc9b900-2564-1075` finished failed, exit 1, with complete/durable output and confirmed terminal publication; there was no timeout, cancellation or automatic retry. The actual formatter made no source change. All eight original canonical merge-graph checks passed, including the reviewed boundary caller-set conflicts and full protected-row multiplicity.

The next committed-source whitespace gate failed with exit 2. The original 42-byte log reports `CALLERS.toml:8120: new blank line at EOF.` Source QA, parser tests, native helpers/tests and full caller proof were not reached. The complete original preparation result, diff-check log and canonical report are retained with their byte lengths and digests.

The separate exact child `7a6c00b8201f685db97ff52bc0b41094b9af1ed2` removes one final LF only; all parsed CALLERS semantics and every other file blob remain unchanged. It requires its own qualification and does not inherit a test pass from v7.

These qualifications do not establish an ordinary positive adoption, ordinary NoUpdate/fallback, or genuine daemon plus Root cold restart. Test custody, fixtures, distinct commit results and incomplete/uncertain control-plane actions remain separate.

## Exact 7a6c native failure, original full proof still running

Source `7a6c00b8201f685db97ff52bc0b41094b9af1ed2`, tree `2aa9a592262d5197cdd96e79128dc18a30332ebd`, job `1a1cccec57a-2564-1088`.

The unchanged source passed 230 source controls and 16 parser controls; the original helper build and verification also passed. The actual native command then exited 100. Its raw log and fresh JUnit agree: **109 selected tests executed, 89 passed, 20 failed; no selected test was skipped and the native command did not time out**. The 1,132 cases filtered out by the exact selection were not executed.

The complete original execution JSON, 129,513-byte raw log, 57,899-byte fresh JUnit, final native result, source/parser logs and canonical graph evidence are retained below `7a6c00b8201f-native-failure/`. Each file was verified against its original byte count and SHA256 before publication. Binary log pagination remained pinned to the same original file version and complete SHA256.

The preparation snapshot and normalized outer-process observation are explicitly interim: the original complete caller proof was still running with an empty log at observation. Neither a terminal overall result nor a full-proof pass is established here. Later evidence must be appended separately. All earlier failure evidence remains unchanged.

A later diagnostic candidate or repair must obtain its own executed results; these failures are not replaced or reclassified. Complete ordinary positive adoption, ordinary NoUpdate/fallback and daemon plus Root cold restart remain **0**.
