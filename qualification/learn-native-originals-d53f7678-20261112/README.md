# d53f7678 original compile and ordinary A evidence

This directory retains the completed d53 runs and their original child logs. The collection operation executed only the explicitly authorized read-only UID0 Python collector; it did not launch Rust or tests, change source, retry the native case, or change its deadlines.

## Exact source and result

- Source: `d53f7678860d6f2ab6b3a6143ea1ceb37bdb2c9f`.
- Tree: `abc89d1ce05ba27f3a56a7601ccfd22de3051b47`.
- Seven-package scoped `just fix`: exit `0`, 112.8809201340191 seconds, clean source unchanged, empty fix patch.
- Ordinary A: one testcase, **0 passed / 1 failed / 0 skipped**, 1.409 seconds. The native driver ran from 2026-11-12T23:07:55.539596+00:00 to 2026-11-12T23:10:50.921019+00:00; that interval includes its preparation and collection work. Source remained unchanged.
- Original JUnit: 3,435 bytes, SHA-256 `c80e7176f94b043d2b2592042828feb7d22eabd4c0460603d5993824619db37d`.

Compilation does not establish a native test pass. This scope contains no Adopt, evaluated post-B NoUpdate, or whole-cold success.

## Actual phase evidence and its limit

The Root child `ordinary-q24-original-process-yi14k1` produced a 1,237-byte stderr. Its recorded remaining frame budget was:

| Recorded phase | Remaining microseconds |
|---|---:|
| ready.frame-received | 499,989 |
| ready.context-returned | 486,991 |
| enrollment.context-before | 347,774 |
| enrollment.profile-before | 335,622 |
| enrollment.profile-returned | 192,714 |
| enrollment.profile-context-returned | 173,874 |
| enrollment.run-start-before | 173,869 |
| enrollment.run-start-returned | 75,629 |
| enrollment.cell-before | 75,626 |

The archive contains these original bytes. No Cell return phase is recorded. Arithmetic on the remaining-budget values shows that 424,363 microseconds had been consumed between frame receipt and `cell-before`; it does not identify the Cell's internal state or cause.

The daemon child `ordinary-q24-original-process-AnQaza` produced a 281-byte stderr reporting a response-length poll with `ready=0`, `deadline_elapsed=true`, no stream/root events, and no OS error. This establishes that poll's deadline outcome. Root signal 9 was cleanup and does not establish an underlying Root or Cell failure cause.

## Archive integrity

- 41 original files, 2,332,530 input bytes.
- Archive: 93,460 bytes; SHA-256 `991d9a9029d1b3329f74e022364ba9159b79bbffe46b0c05753d8078aa8421b7`; Git blob `aa3cc80c083e65031617a72109c4f2ee3df885f5`.
- Manifest SHA-256: `ac8560dd6ddc960167eb1fc73aa01ef2c230c139021e1d7703964bb62149357b`.
- All six download chunks used one pinned H file version; every chunk hash, archive hash, member size, member SHA-256, and member Git blob was verified locally. The collector independently reread the original files after creating the archive and confirmed unchanged bytes.
- Collector job: `1a1d20d50f6-2564-1c95`; key `ci-evidence-collect-d53f7678-20261112-v1-ff41`. Authoritative state `succeeded`, exit `0`, output complete and durable, terminal publication confirmed, no automatic retry or timeout. This is the collector result, not a test result.

`collection-receipts.tar.xz` preserves the exact collector, launch specification, original tool responses, pinned chunk responses, and local verification scripts/results. The first local verifier stopped on a schema KeyError: the native driver names its source fields `head/tree`, while the scoped-fix driver names them `expected_head/expected_tree`. The corrected verifier checks each actual schema explicitly. That local collection check is preserved separately and did not rerun or change either original run.
