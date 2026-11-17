# CI triage for evidence head 9d62fafa

This is a read-only evidence review. The blocking run remains **failed**. No source, assertion, workflow, model run, required check, or approval policy was changed; this review started no workflow reruns.

## Identity and source comparison

The [blocking run 43994639372](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639372) reports head `9d62fafa3713e25fa4c80eaab403e094ef4bc647`. Its six Bazel jobs actually checked out PR merge `477664d4dcbf40b5d65e2b56fdb31f7e7bee0178`, merging that head into `13153e5b0334e8ce883f957161c5cbcd38386f67`. The [head-to-merge comparison](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/9d62fafa3713e25fa4c80eaab403e094ef4bc647...477664d4dcbf40b5d65e2b56fdb31f7e7bee0178) reports **zero changed paths**. Thus the different checkout commit does not establish a source-tree difference for these jobs.

The [v3 source-stack comparison](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/42e32825ae20d460cb782856e00816661536853a...9d62fafa3713e25fa4c80eaab403e094ef4bc647) contains 34 commits and 161 changed paths, all in `V3_BASE.json`, `scripts/cell_experiments/`, or `qualification/cell-experiments-v3-20261116/`. It contains **no Rust, Cargo, Bazel, or workflow changes**. The named Rust assertion files, Cargo dependency declarations/lockfile, and workflows below are unchanged by this stack.

This comparison establishes edit scope. A matching baseline CI run was not examined. It does **not** prove that these failures are harmless, reproducibly inherited, unrelated to all runtime interactions, or eligible for a waiver.

## Final failed jobs and observed symptoms

| Job | Final failed Bazel targets or step | Evidence from the retained log |
| --- | --- | --- |
| [cargo-deny 133743960601](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639372/job/133743960601) | `Run cargo-deny`, step 7 | The job and failed step are confirmed. The **specific failing dependency/rule is still unknown**: only a 1,588,359-byte prefix was recovered before a 60-second download timeout. The prefix ends inside a dependency tree. |
| [Mac ARM 133743961257](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639372/job/133743961257) | app-server, core integration, hepta-agentd, matrix store migration | Executor-skills JSON parsing fails; core zsh/approval assertions fail; the causal fixture returns `Invalid`; research-owner/material tests hit `Not a directory` or `require_unstarted` assertion failure; encrypted restart returns `Initialization`. |
| [Mac Intel 133743961512](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639372/job/133743961512) | app-server; code-mode-host gRPC notifications, TCP, WebSocket; hepta-agentd; matrix store migration | The executor-skills, seven hepta-agentd, and encrypted-restart symptoms match ARM. Code-mode-host tests additionally fail because their endpoint is not published or cannot be reached before the timeout. |
| [Windows 1/4 133743961396](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639372/job/133743961396) | exec-server process test | `remote_windows_sandbox_process_accepts_process_write` receives error `-32603`, with legacy Windows sandbox isolation unavailable. **core-unit-tests is finally FLAKY, not FAILED**; its earlier attempts contain wait-agent timing and resume-cleanup failures. |
| [Windows 2/4 133743961532](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639372/job/133743961532) | CLI cloud sandbox, Windows sandbox unit tests, app-server | Disabled/unavailable sandbox backend messages, a capability denial assertion mismatch, policy-error assertion mismatches and poisoned test locks. App-server also records two deadlines and an image-edit mock expecting one request but matching zero. |
| [Windows 3/4 133743961375](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639372/job/133743961375) | queue, hepta-agentd, hepta-neuron, TUI | Queue hook timeout; `Invalid`, `PermissionDenied`, and OS error 33 file-lock failures in Hepta fixtures; perception fixture byte mismatch; TUI path equality differs by Windows extended-path prefix. |
| [Windows 4/4 133743961401](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639372/job/133743961401) | exec-server Windows filesystem, core integration | Seventeen filesystem test names have failure entries involving unavailable legacy isolation. Core additionally records subagent notification/hook failures, missing files in workspace-roots cases, and an unexpected helper error in the hard-link test. |

`TEST_FAILURES.json` lists the exact unique test names, first failure-block line ranges, observed assertion/error excerpts, panic source locations, and final Bazel target summaries. Repeated attempts and the workflow's repeated rendering of failed logs are not counted as independent observations. A test name in this index means an observed `FAILED` line, not a claim that every individual case remained failed after retry.

### Specific distinctions that matter

On Mac ARM, the core failure messages include missing approval events, approved commands failing to produce the expected output, status `1` versus expected `0`, and an expected sandbox denial replaced by `No such file or directory (os error 2)`. The log also contains escalation/socket errors. These facts support a diagnostic grouping; they do not isolate a common cause.

Both Macs fail five research material/owner tests at `learning_iteration_research_external_material_tests.rs` with `Not a directory (os error 20)`, another at line 158 on `require_unstarted(temp.path()).is_ok()`, and the causal readback fixture at `circuit_cell_test_support.rs:17` with `Invalid`. These are substantive failed checks, including ownership and durability-related behavior, and have not been waived.

Windows 2/4 includes a capability test expecting `PermissionDenied`/OS code 5 but observing `None`, alongside unavailable-backend and poisoned-lock errors. Those are different recorded symptoms; treating all Windows failures as benign environment noise would exceed the evidence.

The Windows perception test at [perception_tests.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/9d62fafa3713e25fa4c80eaab403e094ef4bc647/codex-rs/hepta-neuron/src/perception_tests.rs) compares encoded bytes to the fixture with exactly one final byte removed. Its diff contains an extra decimal `13` on the fixture side. CRLF conversion is a plausible explanation, **not a verified cause**; the runner's actual fixture bytes were not independently collected. The TUI comparison instead exposes a concrete ordinary-path versus Windows extended-path-prefix mismatch.

### Cargo-deny remains unresolved

Two connector attempts reported `Transport closed` to the parent. This review's connector batch also failed without retaining the full error body. A native, read-only `gh api` download retained the prefix preserved here and then timed out. A bounded suffix-range request returned HTTP 200 with no `Content-Range`, so its bytes cannot be called a tail; that request also timed out. A separate check-run annotation read returned one Ubuntu runner-migration notice and no dependency finding. These retrieval receipts are retained in `metadata/RETRIEVAL_RECEIPTS.json`.

The RustSec no-suppression guard and final clean-worktree step passed in job metadata. Neither fact supplies the missing cargo-deny failure reason. No advisory, dependency, license, or ban is guessed from a warning-only prefix.

## Architecture retry: transport failure, lock drift unproved

The [architecture retry job 133757105214](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639113/job/133757105214) explicitly checked out the unchanged head `9d62fafa...`. It failed to fetch `sha1-checked` from the crates.io index, with `[16] Error in the HTTP2 framing layer`.

The recorded dependency chain is:

`codex-cli → codex-git-utils → gix 0.83.0 → gix-hash 0.25.1 → sha1-checked`.

The script subsequently printed `Cargo.lock differs from the exact candidate manifests`; offline resolution then reported that `sha1-checked` was unavailable in the local index/cache. There is no successful locked resolution or concrete lockfile diff in this evidence. **The failed command is real; lock drift is not established by its generic error label.**

## Remaining limits and separate work

The formatter job failed in [Prettier](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43994639372/job/133743960656). The parent owns two quote-only changes to `.github/workflows/cell-experiments.yml` and `.github/workflows/cell-hia-joint.yml` separately. This triage did not apply them, claim their new CI results, or change the frozen evidence head.

The successful Linux jobs and aggregate `rust-ci / CI results (required)` status do not erase the failed Mac, Windows, cargo-deny, or formatter jobs. Cross-platform correctness remains unresolved. Runner environment, cache state, races, filesystem semantics, and source behavior have not been experimentally separated. No extra test runs were started to speculate about them.

These are engineering CI observations. They establish no E1–E6 learning benefit, independent holdout success, user growth curve, useful-work reward, or foundation-model capability.

## Files and byte preservation

- `EVIDENCE.json`: concise machine-readable conclusions and limits.
- `TEST_FAILURES.json`: exact observed test names, excerpts and source/line index.
- `SOURCE_CHANGE_EVIDENCE.json`: comparison metadata and unchanged referenced paths.
- `metadata/`: saved run/jobs/compare responses, retrieval receipts and a short source excerpt.
- `LOG_MANIFEST.json` and `logs/`: seven complete connector-decoded logs plus the explicitly incomplete cargo prefix. Mac ARM's gzip is split into 322,560-byte parts; the other compressed files fit individually.
- `MANIFEST.json`: SHA-256 and byte size of each deliverable, excluding itself.

The seven complete logs preserve the UTF-8 bytes returned by the connector, including BOM/CRLF where supplied; this is not a claim to the original HTTP object's checksum. The cargo prefix preserves raw native stdout bytes, including a potentially incomplete final UTF-8 character. No outcomes or line endings were rewritten. Raw local files were moved outside the proposed Git directory; **every file proposed for Git is smaller than 512,000 bytes**.

To restore a log, concatenate its `parts` in `LOG_MANIFEST.json` order, verify the compressed SHA-256, decompress gzip, and verify the uncompressed size/SHA-256. Use an output directory outside Git; restored logs can exceed the repository's object limit. The archive was checked by actual full-byte reconstruction and decompression, not merely by listing filenames.
