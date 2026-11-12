# Exact ai395 v2 preflight and observed helper failure

Durable job `1a1cf357421-2564-19c6`, key `ci-native-root92817b2f-fresh-target-20261112-ff41-v2`, completed with exit 1. This is separate from v1. Actual preflight observed UID 1000, `sudo -n id -u` returning 0, no existing task-native or unresolved compiler process, and 359,162,687,488 free bytes. The new exclusive target and new checkout were created. The checkout was clean at exact source `92817b2fee9f088a44831ee894d973eff3333853`, tree `c73fae7021766799925e38d6e4ef9268fc5c61f0`, before and after the attempt.

The actual helper command exited 1 after 148.760008 seconds according to its original recorder (149.167121 seconds including wrapper overhead). The complete 198-byte outer helper log only reports `complete: false`; it does not disclose the compiler cause. The terminal wrapper response, original recorder manifest, outer log, exact executed driver and request have been retrieved and preserved. Full compiler JSONL / stderr and the helper manifest had not been retrieved when this evidence commit was written because subsequent reads did not complete. Their absence here is explicit; no reconstructed compiler output or inferred error is substituted. The known fixed diagnostic operation key is `ci-native-root928-v2-diagnostics-20261112-ff41-v1`; its start response is unresolved.

No ordinary or Root test ran and no fresh JUnit exists. The successful sudo preflight is not a Root test result. The target mkdir requested 0755 but the observed host umask produced mode 0700; no later permission correction or independent-UID execution is claimed. The exact source bundle is already preserved under `../root-928-h-preflight-v1/`.

The archive also preserves the independent cloud cache-retirement record: after the 2420 linker process had terminated, only this task's completed incremental cache was removed. Compiled dependencies, build outputs, source and original evidence were retained. This action is not a source change or a successful linker result.

Complete positive / NoUpdate / daemon-plus-Root cold-restart counts remain 0 / 0 / 0.
