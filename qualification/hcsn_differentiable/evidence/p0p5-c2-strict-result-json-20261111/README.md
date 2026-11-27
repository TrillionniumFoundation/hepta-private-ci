# HCSN C2: require valid JSON object for digest-bound exported result (HOLD)

2026-11-11. New **separate Draft-only** P0/P2 structural-evidence repair, stacked at immutable parent #5980 head `7f5bda36fc46b4cbb16136f1f6c49b3f34873bce`. No original C2 process, checkpoint, owner, dataset or unrelated worktree was changed. This does **not** connect a new C2 runner/controller or constitute training replay.

## Independently reproduced fail-open

At #5980, `c2_native_replay.inspect_exported_observations` checked the `result.json` byte SHA but never parsed its JSON. A producer able to rebind terminal receipt SHA could make the structural checker accept:
1. duplicate JSON `schema` keys;
2. a non-finite `NaN` result value;
3. a top-level JSON array rather than an object.

Three deterministic malicious fixtures, all with **matching** result/terminal SHA-256, therefore reached `structurally_matched_count=1` before the fix. This is **not** an attack on the cryptographic SHA function, an authenticated native receipt, or an actual model result; it is a validation gap in untrusted exported observations.

## Narrow change

`recovery_v1/c2_native_replay.py` now parses `result.json` with duplicate-key and nonfinite/exponent rejection, enforces a builtin JSON object, and retains the 16 MiB result-byte cap. Existing strict `resource.json`, POSIX checkpoint and append-only receipt semantics are unchanged. The original reported scientific gate remains `HOLD_NO_GO`. A valid object with an arbitrary schema can still pass this **structural** check; source/model/data/result-semantic replay and native live attestation remain separate obligations.

Exact GitHub blobs (original -> updated):
- implementation: `d896d9ba1081994239a99b706653d55bc748a447` -> `2c32d84877b89f3fb84a1abad91e5c1fe6e424fa`;
- regression tests: `c76cc5ec0a6d4e9f118c9688152a572fca654ebe` -> `fe06ef87794383c53fb29125360fb336889b397c`.

## Native red/green, full denominator

Both test executions used the original C2 desktop interpreter `/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python`, Python **3.12.3**, Torch **2.8.0+cu128**.

- **RED:** heptaruntime desktop native job `1a1cb094794-2564-9b7`, before-source blob from #5980 plus three new regression tests; `21` tests, **3 failures**, inner unittest exit **1**; durable wrapper exit **0** means it correctly detected expected failure, **not** test success. Original output: [RED.native.log](RED.native.log).
- **GREEN:** desktop native job `1a1cb0b8f57-2564-9ca`, new candidate source/tests plus frozen durable/torch interop tests; `39/39 PASS`, zero skipped, inner exit **0**, durable job exit **0**, complete untruncated output. Original output: [GREEN.native.log](GREEN.native.log).
- Green source bytes SHA256 `84f89b1003e333d27d3c89243efb72e813469fae7aeb0f4a4db368a1b4b2451e`, green tests SHA256 `f4e1c72ee3fc41bb8e4ed1669d35d68e88a365c2c7176c97702d8fb81bd50436`; both exact bytes were published as the GitHub blobs above and read back by exact commit.
- These are **39 scoped native tests**, not an entire HCSN CI pass or full-repository blocking-ci pass. Hosted CI for the final evidence-bearing source head must be read separately.

## Frozen original C2 remains unresolved

Independent read-only desktop `file_info` and native `process_status` verified the original `1a1c74f3308-be2a-75` remains `finalizing`, `outcome=unknown`, `terminal_publication_confirmed=false`. Journal: **28,672 bytes**, SHA256 `1405bced8c59a294276616cd7054f2b4068e10d858ab61d78bb578b93992239f`, 16 complete records and a torn 17th. Original controller `RESULT.json` remains absent. Original fit reports stay **4/6 producer `result.json`**, two missing results; `hcsn-s211-lr0.001` and `hcsn-s307-lr0.001` each have a zero-byte `interrupted.pt` (empty SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`). No original unknown-effect work was restarted or repaired in place.

**All P0–P5 scientific/adoption gates remain HOLD_NO_GO.** In particular, no new runner/controller wiring, all-six independent native terminal and model replay, posterior/rare-tail P1 coverage, opportunity/cost-matched P2 comparison, DP/QVI neural advantage, real async multimodal task benefit, or P5 energy/adoption evidence has been produced by this narrow repair.
