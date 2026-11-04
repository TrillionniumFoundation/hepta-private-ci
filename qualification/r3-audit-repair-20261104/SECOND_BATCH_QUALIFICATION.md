# Second-batch qualification evidence

Generated: 2026-11-04T16:53:27.970381+00:00

This package records actual native runs on different fixed source trees. **It does not certify a final combined product tree or close the original macOS/Windows/Linux CI gates.** Original JUnit, status and source-manifest identities are retained in `second-batch-qualification.json`; no raw test-output prompt or local runtime path is reproduced here.

## Original failure accounting

The current mapping at `2026-11-04T16:44:42.431653+00:00` classifies **34 of the 48 original names** as native-pass/awaiting-platform. It separately records **35** names with a latest native PASS. The difference is the PTY drain case, which remains `OPEN_DIAGNOSTIC_ONLY`: its Linux success does not prove that the original Intel cause was repaired. Original-platform closures remain **0**.

The ANSI-corrected original union contains **48 distinct failing test names**. The retained disposition snapshot at `2026-11-04T16:18:57.738672+00:00` has **32 exact native original-case passes** and **0 original-platform closures**. Names are not a root-cause count. The earlier 47-name parser result and failed attempts remain historical evidence.

The 48-name snapshot remains distinct from later reports attached to this package. Newly passing original names received after that snapshot are listed below and are not silently substituted into the frozen snapshot count:

- `app::tests::background_exit_tests::exit_interrupts_before_requesting_shutdown`
- `tests::pty_dropped_output_receiver_keeps_draining_child`
- `tests::pty_preserving_inherited_fds_keeps_python_repl_running`

## Native executions

Each row has a complete JUnit matching its retained status hash, an exact source tree, unchanged-source proof, complete selection and zero retries. A negative-control failure is intentional only where its targeted observation was independently found in the complete output. The whole phase status remains visible.

| Phase | Source tree | Selected | Pass | Fail | Skip | Phase exit |
|---|---|---:|---:|---:|---:|---:|
| `core-ws-mailbox-boundary-units-v2` | `d12e1f208276f8986a5dcb641182ec20316ac4c8` | 8 | 8 | 0 | 0 | 0 |
| `core-ws-production-originals-v2` | `d12e1f208276f8986a5dcb641182ec20316ac4c8` | 8 | 7 | 1 | 0 | 100 |
| `core-mailbox-production-originals-v2` | `d12e1f208276f8986a5dcb641182ec20316ac4c8` | 8 | 7 | 1 | 0 | 100 |
| `core-macos-oracle-lifecycle-originals-v2` | `d12e1f208276f8986a5dcb641182ec20316ac4c8` | 3 | 3 | 0 | 0 | 0 |
| `core-hooks-after-lifecycle-v2` | `d12e1f208276f8986a5dcb641182ec20316ac4c8` | 22 | 22 | 0 | 0 | 0 |
| `core-startup-and-compact-final-oracles` | `7ffccb6da313e843360195f19707c47c062a1e64` | 2 | 2 | 0 | 0 | 0 |
| `agentd-lease-original` | `d12e1f208276f8986a5dcb641182ec20316ac4c8` | 1 | 1 | 0 | 0 | 0 |
| `queue-claim-originals` | `d12e1f208276f8986a5dcb641182ec20316ac4c8` | 4 | 4 | 0 | 0 | 0 |
| `tui-canonical-original` | `d12e1f208276f8986a5dcb641182ec20316ac4c8` | 1 | 1 | 0 | 0 | 0 |
| `rt-causal-original-negative-v3` | `5b22aecf1b93b36ad354fa494529572417d9489f` | 1 | 0 | 1 | 0 | 100 |
| `rt-causal-sync-audio-negative-v3` | `d0ad4ebe0e9bd8b72ad2b380bea0bd89c99921b6` | 1 | 0 | 1 | 0 | 100 |
| `rt-causal-worker-positive-v3` | `36e6bdeee1b35642fb0f5545ba5bb18e19b19475` | 3 | 1 | 2 | 0 | 100 |
| `rt-originals-and-final-oracles-v3` | `36e6bdeee1b35642fb0f5545ba5bb18e19b19475` | 20 | 20 | 0 | 0 | 0 |
| `ws-identity-after-realtime-v3` | `36e6bdeee1b35642fb0f5545ba5bb18e19b19475` | 2 | 2 | 0 | 0 | 0 |
| `rt-worker-final-four-controls` | `8940f5715bc1e3b58fa10e318e24afffe78c29b8` | 4 | 3 | 1 | 0 | 100 |
| `rt-v2-requested-close-original` | `3b5f68e411b88afbf8fa9a44ab4f13e6464bfcb4` | 1 | 1 | 0 | 0 | 0 |
| `app-remote-original-negative` | `0ec7ee504e4450a6a959a437a54363d8634100a9` | 2 | 1 | 1 | 0 | 100 |
| `app-remote-fixed-originals` | `98e7be301dec58f14d51738221e4445e3a06d900` | 19 | 19 | 0 | 0 | 0 |
| `app-lifecycle-and-executor-originals` | `98e7be301dec58f14d51738221e4445e3a06d900` | 14 | 14 | 0 | 0 | 0 |
| `pty-readiness-original-negative` | `d4a0e87482df856490da53e312c460c55a12836f` | 1 | 0 | 1 | 0 | 100 |
| `pty-readiness-fixed-all-originals` | `a3a2526796a0cd8ec30c8d1d5f718a1e1e603e34` | 28 | 28 | 0 | 0 | 0 |
| `tui-interrupt-old-predicate-negative` | `0b76fae93d0f5afc30e7a602c7a7db78dd97c224` | 1 | 0 | 1 | 0 | 100 |
| `tui-interrupt-fixed-all-originals` | `7c4370335115a1eb098c5b88981d9dff24371cf4` | 12 | 12 | 0 | 0 | 0 |
| `app-signal-original-negative` | `1ebbdf67bfec90c4cb43babc15aa3914367fd269` | 5 | 2 | 3 | 0 | 100 |
| `app-signal-fixed-parents-and-drain` | `57b8d27014ac37bc2ea6262b2c6a52fb6c2e33b0` | 5 | 5 | 0 | 0 | 0 |

### Interpretation of the retained failures

- **Core d12:** 49 selected, 47 passed and 2 failed. These two failures are preserved. The later exact startup/compact oracle run passed 2/2 on tree 7ff; it does not erase the d12 results.
- **Realtime baseline:** the combined repair base with original realtime production rejects the second handoff with `NotIdle/BadRequest` while the owner is pending and only one physical model request exists. The six-line synchronous observer separately blocks audio beyond the unchanged 500 ms budget and is excluded from the product.
- **Realtime worker:** the 36e6 three-control attempt passed 1 and failed 2 because its new negative fixture expected two requests while asserting one. Correcting only that internal fixture contradiction yielded three V1 passes on tree 8940. The V2 test's later explicit-close reset failure is retained; the narrow requested-close correction passes the exact V2 case on tree 3b5. There is no all-four-in-one-execution claim. The original realtime/final-oracle 20/20 and identity 2/2 reports are separate.
- **AppServer:** the original handshake baseline records 1 failure and 1 companion-control pass. The failure is the models request reaching the WebSocket handshake without its upgrade header. The fixed original remote group passes 19/19 and the lifecycle/executor group passes 14/14 on tree 98e7. Those 33 selected cases include 11 names in the original 48-name union.
- **PTY:** complete JUnit and status receipts verify the echo-before-execution baseline failure and the repaired Linux 28/28 result on tree a3a25267. The previous expected-30 runner check was wrong for Linux: two original process-group cases are macOS-only. That runner failure, all original budgets and the original Intel gate remain visible. The diagnostic drain case's Linux pass does not establish the original Intel cause or its repair.
- **TUI interrupt/shutdown:** the extracted old readiness predicate fails the real failed-start control with the expected `TurnStarted must not make a failed shell start ready for interrupt` diagnostic. The repaired group passes 12/12 on tree 7c437033, including all 11 original cases and the new failed-start control. The original Windows gate remains open.
- **Signal follow-up (B23):** the baseline has three failed TERM/HUP/INT parents and two passing original drain cases. Each complete child backtrace identifies the timeout at source line 116 (`retained.recv`), after line 115 confirmed independent delivery. The actual native fixture is byte-identical to the reviewed source. The fixed five-case roster passes 5/5 on tree 57b8d270 in 0.089 seconds. This new issue remains outside the original 48-name union. The ignored helper is executed inside each owned child and acknowledged privately; it is not counted as an extra parent pass. Signal registration failure now intentionally propagates before acceptors open. Final product/platform CI remains pending.

## Native platform scope

The directly retained lane receipt observes Linux x86_64 with Rust 1.95.0 at AppServer startup on tree 8940. It is a current same-lane observation, not an independently captured platform receipt for every earlier JUnit. No macOS, Windows, Wine or final Bazel product qualification is inferred.

## Helper dependency generation

| Hosted run | Exact source | Actual inputs | Scope | State |
|---|---|---:|---|---|
| 41851347278 | `ea84b04d25fbb40662414239d4836c0c161900aa` | 805 | Four reviewed Exec Server helper source postimages | `VERIFIED_ORIGINAL_UPDATE_AND_CHECK_PASS_NO_LOCK_DRIFT` |
| 41865994466 | `3dd8aa36c60802312584743e6dcfa73e1e5a29a5` | 806 | Combined four Exec Server and two CLI helper source postimages | `VERIFIED_ORIGINAL_UPDATE_AND_CHECK_PASS_NO_LOCK_DRIFT` |

The first 805-input run covers the four Exec Server helper postimages. The combined 806-input run additionally covers the two reviewed CLI files; the added inventory entry is the CLI test source because its BUILD file was already tracked in the original 805 inputs. Both use the real original `just bazel-lock-update` and `just bazel-lock-check` commands. Their exact step durations, API terminal states and artifact-verification receipts are recorded separately in the JSON. Neither artifact branch is product qualification.

Both hosted runs have terminal-success API evidence and complete artifact verification. Both actual generated locks remain byte-identical to the committed source lock: SHA-256 `11f8a421224b9b05f32c4c14054e8868083d989fc497310c8d51e1156f189ca3`. No lock diff was manufactured.

## Gates still open

- Final product commit/tree and full original CI matrix have not been certified by this document.
- Windows token/legacy outside-delete production failures remain open; helper layout does not change or qualify the restricted production boundary.
- Windows Code Mode approval-path timing remains diagnostic; no cause is closed by native results from a different platform.
- Windows private-state acquisition original positives and two real negative controls remain independent gates.
- macOS Intel PTY drain root cause remains unproved despite the unchanged-budget Linux case passing.
- Additional native reports require complete matching JUnit/status/source receipts before inclusion; no process is polled or started by this generator.

## Reproduce this summary

```sh
python3 generate_second_batch_qualification.py --audit-root AUDIT_EVIDENCE_DIRECTORY --output OUTPUT_DIRECTORY
```

The generator only parses retained evidence. Use `--disposition-snapshot AUDIT_RELATIVE_SNAPSHOT_JSON` to retain a historical count while also reporting the current mapping. Additional signal/TUI result files can be supplied with `--extra-status AUDIT_RELATIVE_STATUS_JSON`; their complete JUnit must be present and hash-identical before inclusion. Run failures, source changes or missing evidence cause a validation error or an explicit pending entry. The enclosing publication should retain the referenced original receipts and the final composed source manifest alongside this summary.
