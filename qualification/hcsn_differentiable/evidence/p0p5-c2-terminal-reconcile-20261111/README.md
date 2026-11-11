# HCSN original C2: read-only terminal reconciliation (HOLD)

This appendix records a **new observation** of the original C2 run, not a training restart, a reconstructed original controller receipt, or a new scientific acceptance. It stacks on HCSN Draft [#5856](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5856) at frozen head `0ea7e54d9b74dcfb237de1c52a6aefbcf0a07823`. Existing evidence and the original source are unchanged.

## Native observations

- Original heptaruntime `desktop` durable job `1a1c74f3308-be2a-75`: `finalizing`, `outcome=unknown`, `status_authoritative=false`, supervisor disappeared without a confirmed terminal receipt. A separate `service_status` read found the named unit **not found**; neither implies successful completion.
- The original `RESULT.json` was **missing** on a read-only file check. The command log at `/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/c2-native-execution-20261110-c385-v1/commands.jsonl` had **28,672 bytes**, SHA-256 `1405bced8c59a294276616cd7054f2b4068e10d858ab61d78bb578b93992239f`.
- The archive `COMMANDS-original.jsonl` below is a byte-exact UTF-8 copy of that original log. Its first **16 lines decode as full JSON**. **Line 17 ends mid-command** and cannot be admitted as a terminal event. Four of the six candidate names have producer-reported `completed` and `terminal_evidence_complete=true`; **no independent all-six qualification follows**. The last full journal record still leaves `hcsn-s211-lr0.001` and `hcsn-s307-lr0.001` unresolved.
- One bounded `ps` sample did not find the sampled former controller/child PIDs. The host reported 40 GB free and 96% filesystem use. Neither observation establishes why supervision or the journal ended.

## Reproduce the bounded finding

Compare the SHA-256 of `COMMANDS-original.jsonl` with `REPORT.json`; parse each newline-delimited record and report both the count of complete valid rows and the malformed final line. Read the **last valid row per candidate** rather than treating an earlier running/terminal row or partial JSON as authoritative. The full original controller RESULT, complete native terminals and independent all-six replay remain prerequisites. The historical C2 tests and numerical failures are not recast as passing.

**Status: HOLD_NO_GO.** Do not restart, change, or relabel the original attempt. Any recovered originals, attempted reconstruction, independent terminal audits, resource envelopes, new training or follow-up experiment must have **new source and evidence identities**. No production activation or Adopt is permitted on this record.
