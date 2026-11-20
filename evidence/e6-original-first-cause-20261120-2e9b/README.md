# E6 original first-cause preservation — 2026-11-20

This evidence commit records the exact tested source `27d90883ce4353c6101f02853f0b585837451ece` (tree `3faacc83f630ca107ecf1f2ed36bbc3fd1f9a0f9`). It does not qualify the complete NoUpdate chain, Adopt, cold D or FinalUse.

## Product change and actual result

The historical delivery owner previously returned the delivery error before the continuation error even when continuation failed first and canceled delivery. The source change retains both owned futures, records which original failure was observed first, cancels through the original tokens, and returns the original first error. It does not reopen an owner, retry a claim, renew a signature, alter a budget, or bypass any witness predicate.

Actual original native validation on this source: **11 passed, 0 failed, 0 errors, 0 skipped**, process exit 0. Command elapsed 103.432589 seconds; owner elapsed 107.958249 seconds. Original scope/filter and offline locked dependencies were retained.

The actual original complete NoUpdate parent then failed: **1 failed testcase, 0 errors, 0 skipped**, process exit 1. The first original continuation error is now preserved both in the daemon log and in JUnit:

```text
GenerationFenced("original post-A Q24: original C predecessor or new witness history differs")
```

The continuation failure preceded delivery cancellation. This confirms error propagation; it is not a successful C handoff. The original C predecessor gate remains unchanged.

Original NoUpdate parent UTC window: 2026-11-20T05:03:02.988513Z to 2026-11-20T05:04:12.791054Z. Testcase elapsed 68.959 seconds; enclosing owner elapsed 125.906260 seconds. Helper build, product build and library build were recorded separately as 33.319988, 7.284261 and 2.069616 seconds. The persistent pipeline owner `dpty-6d9ed07abdb35147aeb9ebb51c453c781768434cd29894276b07ee3c183b325a` exited 1 with complete output capture and no capture error.

## Original gates and failed candidates

The first source-only candidate is preserved, including its **244 tests / 60 errors**, caused by replacing the protected `if result.is_err()` form. No verifier or protected-order manifest was weakened. The second source candidate restored the original guard and passed **244 tests, 892 protected rows, targeted caller verification, and the original 1,137-boundary caller CLI**. The latter owner elapsed 563.036902 seconds, including 466.782845 seconds for the full caller CLI.

The archive also retains the earlier `715a7a370ea8a00940805be4008b6e88da0ff8c1` diagnostic round: actual original native **11/11 passed**, followed by the failed NoUpdate parent that exposed a masked `CommitUncertain`. Its retained source stdout reports one passed test in 4.06 seconds; that stdout is not an independently captured kernel wait result.

## Exact originals

`original-evidence.tar.xz` contains 177 original files (42,104,141 bytes) plus its internal `MANIFEST.json` and `COHOST_ACTIVITY.json`. Every original file is listed with size and SHA-256. The archive includes the original source gates, raw native stdout/stderr and XML, parent XML and summary, unchanged protocols, runner code, tracked inventories, compiler/ELF checks, freeze receipts, prior NoUpdate7 result, and source diffs.

The archive is **1,022,756 bytes**, SHA-256:

```text
86d5642e3ac2eab2362c0d0e4b3f13e60b9ea2d0f4a308ea1c18b0ada9e0fef5
```

Internal manifest SHA-256:

```text
d25ff7e4d69bd11b4d183bb7018d32db8235a0257adffb0ec41eded41128c91a
```

Key original result hashes:

| Original | SHA-256 |
| --- | --- |
| Source gate 2 RESULT | `3dd7a6d7177d0451f80a0577dd0ddb941b835c2f2edfe95b8967bd7bff0e4cb4` |
| Source freeze RESULT | `d0a9bdb5c84cbdc5ac7e641b781862c60650cc4b1cc0a08fefec852940aefa6a` |
| Native 2 RESULT | `4f088878f30d696726e0be823b2548e54d0b2a9b38a42f0f493402dda39ceef1` |
| Native 2 XML | `83761068f210e436175bdfd783f3fc340e068ec6443a4074c540cf68f2893c6f` |
| NoUpdate 2 RESULT | `d4a11ec5bc1a0cffbde46eecb82ff306cfd199e0a6eefeea43dbc2e0e5f16cd8` |
| NoUpdate 2 XML | `b7f12857efdc12169bc08253be1baa6707f9e6bf759bb8addcbd3371c5179460` |

Compiled prior ELF files, quarantined CMake outputs and Python caches are explicitly listed as exclusions; they remain at their original isolated host paths. This archive is a reproduction/evidence bundle, not a complete compiler cache or a claim that excluded binaries are embedded.

The original 64-read ceiling, 500 ms frame and 240/300/600-second authority/deadline conditions remain as originally defined. No retry, budget increase, acceptance-score change or production activation occurred. Source, compiler and ELF checks stayed unchanged across the actual parent; original mount cleanup passed. Original earlier generations and failed inputs were retained.

## Measurement limits

The cohost file records the other agent's final CPU job before the parent and small read-only RPCs whose individual UTC bounds are unavailable. No concurrent native/build/compression job was reported during the parent. We do **not** claim zero cohost activity or complete whole-system cost accounting. Enclosing owner times include different build and orchestration work and must not be conflated with testcase time or process CPU.

The original Adopt CURRENT 240-second versus retained writer 300-second expiry conflict remains unresolved. This evidence does not extend or substitute either owner authorization.
