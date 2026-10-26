# Standalone native composition and new driver qualification

The isolated native harness passed its 20 offline tests, formatting, strict all-target Clippy and final build. A separately built runtime driver then passed two real controller-crash cases and six read/old-operation lookup calls. These results establish the bounded composition and recovery routes described below. They do not establish a completed model/tool/model loop, production authorization, a smaller release binary or a performance advantage over Codex.

This is a later evidence snapshot for source PR #3976 and evidence PR #3979. The earlier `20261026-provider-runtime-status` snapshot remains immutable. In particular, the original runtime full result remains **1,151 passed / 3 failed / 21 ignored**, and the original live model marker remains **HTTP 400 / model_not_found**. No cap, two-round generation or primary three-arm comparison is admitted by this snapshot.

## Exact composition

| Input | Recorded identity |
| --- | --- |
| Hepta CI checkout | `e21e1054a0f9e7a63e4e77b8e06fac71d42f6375` |
| Runtime base | `d4d48189d03b8ff8dfe8d82652b749fb44cd9d50`, plus the recorded unstaged lookup/example changes |
| Final generated harness | `provider-runtime-process-standalone-v4`; its complete generated source and inventory are included |
| Harness compiler | Rust/Cargo 1.96.0, checked by the actual runner |
| Actual harness Cargo lock | 301,613 bytes; `aeb5245e915cbe50f99db0e847595c9303324be5c7187790306ad1df5bf6ad15` |
| Original source authority | The original CI/runtime HEAD, index and complete build-input inventories were checked before and after each recorded stage |

The exact generated source is a derivation outside the unchanged source PR. The harness uses the existing runtime driver process because the initial same-process dependency combination could not resolve the original incompatible rmcp requirements. That process boundary has a cost which has not yet been measured in a fair live comparison. It is not a requirement that every future logical module use IPC.

## Actual gates and retained failures

| Stage | Actual result | Qualification limit |
| --- | --- | --- |
| Earlier process-composition builds | MSRV and effect-key error-binding compilation failures retained in v1/v2 | These attempts did not pass Rust tests |
| V3 offline tests and formatting | 20 passed; no failure, ignore, filtered case or retry; formatting completed | Tests precede later formatting and lint stages |
| Later V3 strict Clippy | Runtime example passed; standalone admission method failed the eight-argument lint | The original failed stage remains included |
| V4 offline tests | **20 passed**, zero failed/ignored/measured/filtered and no retry | The borrowed-input correction has its own actual gate |
| V4 formatting | Passed; no generated source change was observed | Tests were not rerun after formatting |
| V4 strict Clippy | `cargo clippy --locked --all-targets -- -D warnings` passed | A standalone gate, not the failed full-runtime suite |
| V4 final build | Passed; actual Cargo executable artifact recorded | This is a debug build and did not invoke the live harness |
| New runtime driver build | Passed with unique actual Cargo example artifact | Old-driver crash results were not inherited |
| New-driver crash tests | Both bounded cases passed | Same-account, explicitly owned canaries; no reboot or production FinalUse qualification |
| Read and old-key continuity probe | Six calls passed; no new process start/status/cancel call | The 111-byte artifact is a local fixture, not model/worker output |

V4 replaces seven separate borrowed admission inputs with one borrowed input object. It does not change the original admission body, owner identity, reservation, request digests or ten-second admission deadline. The earlier eight-argument lint failure is not erased or disabled.

The V4 test command took 489.796411302 seconds, including compilation/linking. Strict Clippy took 7.096759377 seconds and the final build command took 26.922366674 seconds. These are build-stage wall times, not runtime latency benchmarks. The final build did not execute the 20 tests again.

## Built executable identities

| Executable | Bytes | Build profile | SHA-256 |
| --- | ---: | --- | --- |
| `hepta-provider-runtime-research` | 1,713,388,712 | opt-level 0, debug info 2, debug assertions enabled | `16c96c974de50a69c3dd7fd918921b568d5a050c3b6e9620a3abe2a93dd96652` |
| `native_process_driver` | 264,189,336 | opt-level 1, debug info 2, debug assertions enabled | `14596a1b4324ac7eb2453515f71439b5827bda68821d7775252a416b37c20205` |

The archive excludes both new executables and the preserved 263,976,104-byte previous driver. Their actual build receipts, compiler artifact records, hashes and original paths are retained. The archive supports evidence review and reconstruction of inputs with the separately pinned repositories; it does not contain executable binaries or an entirely standalone offline build distribution. Comparing these debug sizes with a release Codex binary would be misleading.

## New driver recovery and read behavior

Each crash case actually killed its own controller with SIGKILL. Each operation retained one worker entry and used four same-key lookups. Changed-payload reuse was refused, unknown-key lookup returned null, and there were **zero post-fault replacement start calls**. The original worker and process-job deadlines remained 40 and 45 seconds. The complete report is 109,827 bytes, SHA-256 `3ea43fab535a5fd27e5d141b71aa860d9247e443a8a22f6d161b310a118b60a1`.

The independent follow-up sequence was validate, file-info, expected-version binary-read, file-info, then two original-key lookups. The nonce fixture was 111 bytes and its size, content, version and SHA agreed through the actual runtime read route. It was deliberately created as a local test fixture; no runtime write API or extra worker job produced it.

The two old references remained `1a1738ff677-14fc73-1` and `1a173902f7d-150467-1`. Both retained one worker entry. The specifically listed original reports, configurations, requests, registry bytes/inodes/mtime and worker markers remained unchanged. Runtime initialization still opens its controller locks and may update directory metadata; this is not a claim that every filesystem metadata bit stayed unchanged. The six-call report is 10,028 bytes, SHA-256 `0bc19becf7db2a758395b2e6cff9bcd96a18d7973d9aace280181c870ab4de69`.

Neither same-key lookup nor receiving a successful final reply creates a new effect owner. The tests exercise recovery through the existing runtime owner. They do not give the parent loop authority to repeat an operation whose effect remains uncertain.

## Evidence map

Paths below identify original archive members. Full per-file sizes and hashes are in the exact internal `SNAPSHOT_MANIFEST.json`.

| Evidence | Archive member or directory |
| --- | --- |
| First process build failures | `evidence/runtime-provider-process-build-v1/`, `evidence/runtime-provider-process-build-v2/` |
| V3 tests, formatting and driver build | `evidence/runtime-provider-process-build-v3/` |
| Preserved strict-lint failure | `native-runtime-scoped-clippy-v1/` |
| V4 source preparation and all gates | `evidence/runtime-provider-process-build-v4/` |
| Final generated harness source/lock/recipes | `provider-runtime-process-standalone-v4/` |
| Actual runtime example and lookup input files | `runtime/` |
| New crash fixture, raw calls, jobs, output and report | `evidence/runtime-controller-crash-new-driver-v1/native-readonly-crash-f6do5_2k/` |
| Six follow-up calls and original-key continuity | `evidence/runtime-driver-readonly-v1/` |
| Exact preparation, correction and canary packages | Top-level `runtime-*.tgz` members |

The archive has **515 original payload files**, 50,615,961 bytes before compression, plus its 113,057-byte internal manifest. The compressed file is 14,112,891 bytes, SHA-256 `aa4483578add12173afd7ff2480201e6c029e761bcf57a7a8f58097aeae35b9e`.

The repository limits an individual new blob to 512,000 bytes. The exact compressed archive is therefore stored as 29 ordered parts, each at most 500,000 bytes. `PARTS_MANIFEST.json` binds every part and the concatenated original bytes. No original member is dropped, recompressed or rewritten, and the blob policy/allowlist is unchanged. `python3 verify_archive.py` reconstructs a temporary copy, checks every part and the original whole-file identity, then uses the pinned previous verifier to check every safe member and its original manifest. It does not execute archived programs.

The capture compared every selected source/evidence file again after archive creation, then read every complete archive member and compared its bytes. It did not execute archived code, rerun tests, contact a provider or modify original source/owner content. Reading can affect filesystem access metadata; the receipt does not claim a universally write-free host.

Two earlier capture launchers failed before creating an output archive: the first required an instruction file absent from the original build-input inventory; the second found an auxiliary package not yet copied to the host. Their original launch/status records are retained separately. The successful capture uses a fresh output path after those preconditions were resolved; no test or source gate was repeated for publication.

## What remains open

The original full-runtime/ext4 gate, actual original-model generation, provider hard-cap evidence, complete two-round continuation, production context/FinalUse admission and fair Codex/native performance comparison remain separate unmet gates. Later official Codex metadata, transport retry controls and platform/CI fixes have their own source combinations and evidence; they are not silently included in this snapshot.

Cell V4 and NDU scientific reports remain in #3942, #3943 and #3974. These engineering passes do not turn their negative or unresolved comparisons into evidence of cell-network growth or general intelligence.
