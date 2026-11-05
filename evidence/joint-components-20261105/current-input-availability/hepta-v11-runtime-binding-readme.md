# Cell runtime binding evidence — 2026-11-05

This directory retains the completed source-admission, schema-consumer, scoped build, and native-test observations for the Runtime candidate paired with Chain execution source V11. It includes failed preparation and native-test attempts, the exact successful source-probe output, and explicit cleanup receipts. It does not establish an ordinary model run, model Ready, installation approval, or product qualification.

The second full-package native `nextest` attempt ended with a linker Bus error and exit 101, before any test assertions ran. A subsequent library-only run ended with exit 100: **181 tests run, 161 passed, 20 failed, 16 skipped**. All eight newly added Python-runtime admission fixtures passed within that run. A separate Cell CLI run passed **3 of 3 tests**, with no skipped tests and exit 0. These are terminal observations, not a passing full-package gate, and they belong to the premerge source boundary below.

## Pinned source identity

The candidate uses [smollm2-public-initial-v2.execution-sources-v11.json](../../codex-rs/hepta-learning-artifacts/profiles/smollm2-public-initial-v2.execution-sources-v11.json). The actual [second source-probe output](logs/runtime-v11-source-probe-attempt2.log) reports:

| Field | Value |
| --- | --- |
| Execution profile | `hepta-integrated-chain-execution-v11` |
| Chain commit | `cfa57cd04751427451302b5c10539b3984d7f8db` |
| Chain tree | `155213c2468edc411325f4f1853b471a6b25f355` |
| Verified source files | 53 |
| V11 manifest SHA-256 | `a951e866f66b0e251fc5a9f81d02a7f86954d1b3ca8ac483890fcb23a4955647` |
| Historical profile SHA-256 | `695d12e8dce5c289a063effdbcc2289148b4708a4a6ead77199da734e0dba2c8` |
| Historical sources SHA-256 | `c4a529e9710f18feaa4996457991876d3999d36bdde285903e72d7180f8bbd0c` |
| Installation authorized | `false` |
| Model compatibility changed | `false` |
| Product qualification | `false` |

The probe output uses the verification-result schema `hepta-smollm-public-initial-execution-source-verified-v1`; the source manifest uses `hepta-smollm-public-initial-execution-sources-v2`. These are different record types. Neither schema suffix is the execution-profile number.

### Premerge source boundary

The retained tests and builds ran on the Runtime working candidate based on `7530e4bc7aa61a0c23a5933fef4a65d86a586cf8`. The [native source projection](receipts/native-source-projection.json) identifies 9,418 declared inputs using that base plus 27 changed/new rows; it explicitly excludes other historical documentation/evidence and does not claim whole-repository raw verification. The separate [runtime-admission-frozen-files.json](receipts/runtime-admission-frozen-files.json) pins 38 files across the paired checkouts: 27 Runtime files and 11 Chain files. Evidence packaging rehashed all 38 and found no drift. These records supply the premerge source identity without claiming a final merged commit was tested.

The original source pairing remains V11's explicit cfa/tree155 identity. The integrating owner's [Chain publication receipt](receipts/chain-publication.json) records delivered commit `cbead1508ce8b6d9deb2a86b4bc3181da09694e7`, tree `624c8aad419ee05dc71a4aac507abea429018289`, with cfa as an explicit parent. It separately associates 194 Python/source controls with local `4771f7b46276f65cc7ca558b31056194d83a7de2`, the same-tree GitHub commit `22ef7177e3c4e119911bf7d657af5c2d1a83ee03`, and tree `a82804baeca600b2cf66c83411545b4563884fe1`. The delivered tree preserves 42 later documentation/evidence files and the receipt reports no production-source changes relative to that checked integration. The [command receipt](receipts/cell-final-integration-source.json) and [raw log](logs/cell-final-integration-source.log) are retained. These Chain observations do not change which Runtime source candidate ran the native commands.

## Versioned runtime and host contract

The implementation and its limits are described in [PYTHON_RUNTIME_CONTRACT_V2.md](../../codex-rs/hepta-infer-worker-host/PYTHON_RUNTIME_CONTRACT_V2.md) and [CELL_HOST_V2.md](../../codex-rs/hepta-infer-worker-host/CELL_HOST_V2.md). The migrated call sites use the following explicit versions:

| Record or boundary | Current version |
| --- | --- |
| Ordinary persisted owner | `hepta-smollm-cognitive-host-v2`; CLI `owner-v2` |
| Cell outer host | `hepta-smollm-cognitive-cell-host-v2`; CLI `cell-v2`; nested ordinary owner is v2 |
| Neural-read worker plan, Ready, reply, and STOP | `hepta-smollm-neural-read-worker-v2` |
| Native check input | `hepta-smollm-neural-native-check-v2`, with required runtime snapshot path and SHA-256 |
| Controlled Cell native input | `hepta-smollm-controlled-cell-native-check-v2`, containing the native-check v2 input |
| Bound execution digest domain | `hepta-smollm-runtime-bound-execution-v2`, including runtime snapshot identity |
| Inference request | `hepta-smollm-inference-input-v1` |
| Semantic action-score model profile | `hepta-smollm-single-token-action-score-v1` |

The unchanged inference-request and model-profile versions do not authorize accepting an old owner, worker, or native-check record at a v2 boundary. The ordinary and Cell handoffs require an independently pinned runtime snapshot; an old result or capture performed only at load time cannot supply that identity.

The public-initial workflow selects execution source V11. Its ordinary three-round and observed/live-control paths invoke the Chain child/parent-step route, rather than the legacy `hepta_neural_forward_v1.py` worker-v1 route. The V11 controls retain an explicit refusal for consuming this profile through that old forward path. Historical study workflows still using native input v1 are a compatibility limitation of this candidate and have not been rerun as upgraded studies.

## Completed observations

The [machine-readable summary](receipts/verification-summary.json) distinguishes log-supported results from process-exit observations supplied by the integrating agent.

| Gate | Observed result | Retained evidence and scope |
| --- | --- | --- |
| Execution-source profiles V1–V11 | **116 tests, PASS** | [Full log](logs/runtime-admission-source-v1-v11-tests.log), terminal `Ran 116 tests` / `OK` |
| Chain admission and handoff controls | **44 tests, PASS; 0 skipped** | [Full log](logs/runtime-admission-post-versioned-tests.log); includes actual Cell transport/exec-contract controls, without a model-load qualification claim |
| Descendant/research consumers after native-input version migration | **12 tests, PASS** | [4 descendant boundary controls](logs/runtime-admission-descendant-schema-tests.log) and [8 research controls](logs/runtime-admission-research-schema-tests.log); these are consumer/boundary tests, not 12 independent model tests |
| Separate V11 control run | **9 tests, PASS** | [Full log](logs/runtime-admission-source-v11-controls.log); retained as a separate run, not added to the 116 as a claim of unique test coverage |
| Scoped `just fix` for `codex-hepta-infer-worker-host` | **Exit 0**, observed by the integrating agent | [Full log](logs/hepta-host-fix-attempt1.log); Rust 1.96.0, original dev profile, `Finished ... [unoptimized + debuginfo]`. The log retains 40 `sqlx-sqlite` dependency warnings and its duplicate warning summary. |
| Format check after the fix | **Exit 0**, observed by the integrating agent | [Raw empty log](logs/hepta-format-after-fix.log). The success claim comes from the observed process completion, not from the file being empty. |
| Runtime structural preflight | **199 local manifests, 0 errors** | [Earlier retained preflight log](logs/runtime-admission-preflight.log). Packaging independently reran `python3 -I -B scripts/hepta_workspace.py` with exit 0 before writing this directory. |
| V11 exact source probe after explicit preparation | **53 source files verified** | [Actual probe JSON](logs/runtime-v11-source-probe-attempt2.log), matching the commit, tree, and manifest digest above |
| New Python-runtime admission fixtures | **8 passed within the library run** | [Terminal library log](logs/hepta-host-nextest-library-attempt1.log); interpreter/snapshot identity, original budget, inventory, ZIP, `._pth`, and standard-library alias refusal controls |
| All newly added Rust controls in this patch | **12 passed within the library run** | [Selector/status receipt](receipts/runtime-native-introduced-test-status.json): the eight admission fixtures plus owner-schema, loader-environment, native-schema, and execution-profile controls. These are included in the 161 passes, not additional tests to add to that total. |
| Separate native Cell CLI controls | **3 tests, PASS; 0 skipped; exit 0** | [Full terminal log](logs/hepta-host-nextest-cell-cli-attempt1.log). These three tests are distinct from the library's 181; they verify actual argument dispatch and strict decoder selection without loading a model. |

The `just fix` log retains the recipe's command family and actual compiler output. Its successful package scope, Rust version, and exit status were supplied by the integrating agent's process observation. This archive does not reconstruct an unrecorded full shell argument vector.

## Failed attempts retained

These attempts are part of the record and are not counted as successful gates:

| Attempt | Observed failure |
| --- | --- |
| [Host check 1](logs/hepta-host-check-attempt1.log) | `openssl-sys` could not find `pkg-config` / the OpenSSL installation. |
| [Host check 2](logs/hepta-host-check-attempt2.log) | The `hepta-fleet` `include_str!` for `docs/modules/MODULES.json` failed because that input was absent. |
| [Nextest 1](logs/hepta-host-nextest-attempt1.log) | The runner `--config` argument led to full Cargo metadata resolution. Offline resolution could not download `accessory v2.1.1`; the `test` recipe exited 102 before tests executed. |
| [Nextest 2, full package](logs/hepta-host-nextest-attempt2.log) | Linking the `hepta-infer-worker` binary test failed with signal 7, Bus error; the command and recipe exited 101. Zero native test assertions executed in this attempt. |
| [Native library follow-up](logs/hepta-host-nextest-library-attempt1.log) | Exit 100 after 181 tests ran: 161 passed, 20 failed, 16 skipped. The full native gate remains failed; observed error categories are detailed below. |
| [V11 source probe 1](logs/runtime-v11-source-probe-attempt1.log) | The strict verifier refused untracked or ignored inputs in the Chain checkout. |

The source-probe refusal was followed by an explicit, separately recorded preparation step: the integrating owner removed only 11 rebuildable Python cache files generated in this task's Chain checkout, totaling **286,001 bytes**. The [preparation receipt](receipts/v11-explicit-cache-preparation.json) lists their relative paths, sizes, and hashes. The verifier was not relaxed, and the refused attempt was not rewritten. The subsequent successful probe is retained as a distinct attempt against the exact V11 source identity.

The [link-failure and reclamation receipt](receipts/runtime-nextest2-failed-link-reclamation.json) records that a complete library-test ELF and `cell_host_cli` integration-test ELF already existed when the worker binary test failed to link. Their existence does not mean they executed in that failed package attempt. It also records the exact incomplete linker temporary that was later removed after identity rechecking; completed binaries were preserved. Storage exhaustion is consistent with the observations, but signal 7 alone does not prove its kernel cause.

The library follow-up's [20 terminal failure blocks](receipts/runtime-native-library-failure-blocks.json) are preserved with selectors and raw error text. The [independent classification](receipts/runtime-native-library-failure-classification.json) records each test's defining source and confirms those defining files are unchanged from base7530. That observation does not promote a failed test to a pass. Its cause attribution is deliberately limited to what the errors establish:

| Failed tests | Observed error and limit |
| --- | --- |
| 2 `native_app_server` tests | The nested test reports `codex` binary `NotFound`, including the `CARGO_BIN_EXE_codex` / `NEXTEST_BIN_EXE_codex` lookup and fallback. These failures are not classified as EPERM. |
| 6 neural failure/session tests | The inner panic identifies `UnixListener::bind` test locations and `Os { code: 1, kind: PermissionDenied, message: "Operation not permitted" }`. |
| 12 final-use, clock, and study-role tests | The log reports bare OS error 1 / `Operation not permitted`. Their source uses Unix test-service setup, but the raw errors provide no syscall backtrace; no per-syscall trace is claimed. |

These classifications do not reclassify failures as passes. The library run also skipped 16 tests, which remain unexecuted observations here. Completing `just fix`, passing Python controls, or the 12 new Rust controls passing does not replace a passing full-package result.

After the library run had terminated, the completed 1,271,890,896-byte library-test ELF was reclaimed for cache space. The [reclamation receipt](receipts/completed-runtime-library-elf-reclamation.json) retains its SHA-256, the terminal test result, and the observation that no library-test process remained active. This was cleanup after the recorded run; the raw results and frozen sources were retained.

## Independent counterexamples and native-test boundary

The paired Chain commit contains the independent, real-CPython review under `evidence/cell-python-runtime-review-20261105/`. That archive preserves the metadata-discovery regression and corrected control, raw-source/bytecode and project-shadow controls, actual startup-ZIP and executable-adjacent `._pth` counterexamples, and the explicitly withdrawn alternate-venv hypothesis. Those experiments did not load a model.

Runtime's [eight runtime-admission fixtures](../../codex-rs/hepta-infer-worker-host/src/smollm_python_runtime_tests.rs) cover interpreter identity, required snapshot data, retained deadline/cancellation, pre-spawn standard-library hashing, undeclared installed files, startup ZIP, executable-adjacent `._pth`, and standard-library alias replacement. All eight actually passed in the retained library run. The ZIP and `._pth` fixtures assert the corresponding pre-spawn refusal. They use filesystem fixtures and a nonexecuted interpreter placeholder; they are not new executions of the original real-CPython canaries. Production calls snapshot verification before spawning the Python session. The successful fixtures substantiate their refusal controls without supplying a model or closing the other failed/skipped package tests.

The implemented admission and loader controls bind a bounded runtime inventory, reject detected drift before the relevant execution boundary, verify imported Python source bytes, and check loaded native mappings before Ready. They do not establish an immutable held runtime namespace. Kernel/bootstrap and system-loader assumptions, same-path check/use races, and dynamic loader search behavior remain limitations documented by the runtime contract. This evidence also does not establish complete model semantics, expert ABI compatibility, GPU/VRAM ownership, independent WAN behavior, independent administrators, or long-term funding.

## Provenance, integrity, and completion

`logs/` contains byte-for-byte copies of the completed raw logs from this task's `verification/` directory, including both terminal native attempts. [raw-log-provenance.json](receipts/raw-log-provenance.json) records each original relative name, byte length, and SHA-256. The source-freeze, cache-preparation, failed-link reclamation, and native selector/failure receipts are also copied exactly. No large runtime snapshot, model data, live compilation log, or complete environment dump is included.

[SHA256SUMS](SHA256SUMS) covers every other file in this evidence directory, including this README and the JSON receipts. Verify from this directory with:

```sh
sha256sum -c SHA256SUMS
```

## Later integration boundary

The later concurrent Runtime source `f55752abbf516febfa0db89cb833dcf1fd1a2221` and a final merge with it are outside these premerge observations. This archive supplies the source base and patch manifest; it does not require an intrinsic self-reference to the commit that eventually carries these evidence files. A subsequent typecheck, test, or publication observation must identify its own source and be retained as a distinct follow-up. Earlier results must not be inherited as a full native or model qualification of that later merge.

If the archive changes, its hash index must be regenerated so that the final checked files remain reviewable. The source manifest and overall development plan were not changed by evidence packaging.

## Completed integration typecheck follow-up

The premerge working source is preserved as GitHub commit
[`72fd6ad2d665489d64271b6c3146debbd201df4d`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/72fd6ad2d665489d64271b6c3146debbd201df4d),
tree `3a4ef7e082bd64cdd8a73b857810992713909cef`. Its commit was created after
the native observations, with the frozen source bytes preserved. The original
base plus patch/source projection remains the description of the executed
working candidate.

Two later merge-source snapshots completed the original scoped
`just fix -p codex-hepta-infer-worker-host --locked --offline` recipe with exit 0:

| Source snapshot | Identical locally checked tree | Actual result |
| --- | --- | --- |
| `944081590d815995f2210528c6d1fef99b6db191` | `d457fbe5797a54c7b73a94d3effd5b3806b83daa`, local `b8b6559e680f3e6eea2a4a89a31192f832d2527a` | Scoped Clippy/typecheck exit 0 after preserving recovery/sealed-qualification changes |
| `3e96ece120cda5cbf75b84f05edc2edb15d41000` | `1b64fd14890e6db0e4a26ced0f151c94629f2ca7`, local `d1c851d06446d4127bfc37139635861a0b9d7eeb` | Scoped Clippy/typecheck exit 0; final `just fmt --check` exit 0; tracked source unchanged |

The second snapshot also preserves upstream `9438a6c`, whose only change
removed an unused `pretty_assertions::assert_eq` import from an agentd test
file. [The follow-up receipt](receipts/integration-followup.json) identifies
the commands, original toolchain/profile, actual exit observations, final raw
project-input projection and unchanged 38-file freeze. Raw logs are retained
[for the first merge](logs/hepta-host-fix-after-integration.log),
[for the final source](logs/hepta-host-fix-final-source.log) and
[for the final format check](logs/hepta-format-final-source.log).

These are compile/lint/format observations with zero new test assertions. They
do not replace the failed full-package or library gates, repeat the premerge
161 passes, or qualify a model, device, installed host or ordinary FinalUse.
The original 40 SQLx dependency warnings remain in the logs.

The local and GitHub raw commit objects are retained under `receipts/` so the
source hashes and tree equality can be verified independently.
[integration-log-provenance.json](receipts/integration-log-provenance.json)
records the additional exact raw copies. The final delivery adds this follow-up
evidence while retaining the checked source snapshot as an ancestor.
