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

Neither qualification establishes an ordinary positive adoption, ordinary NoUpdate/fallback, or genuine daemon plus Root cold restart. Test custody, fixtures, distinct commit results and incomplete/uncertain control-plane actions remain separate.
