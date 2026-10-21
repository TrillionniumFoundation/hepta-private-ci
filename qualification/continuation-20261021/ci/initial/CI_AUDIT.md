# HEPTA CI evidence snapshot

Collection window: 2026-10-21 00:40–00:49 UTC. Repository: `TrillionniumFoundation/hepta-private-ci`.

This is a bounded live CI investigation, not a claim that every historical workflow or every PR is qualified. GitHub snapshots are not atomic; head identities and retrieval scope are retained below. The raw data and original downloaded logs are in this directory. Do not commit the approximately 28 MB raw collection by default; the summaries, selected excerpts and hashes provide a small review surface.

## Protection and access

The observed `main` is `f8c9419df6ddeb36ff8b522a50219981fb8d9345`. Its branch response reports protection enabled and required contexts `CI required` and `Architecture required`, both associated with app ID 15368. The response reports enforcement level `non_admins`; this is not authorization to bypass checks.

- `GET /branches/main/protection`: integration returns 403, `Resource not accessible by integration`. Full review, freshness and administrative rules could not be inspected through this connection.
- `GET /rulesets?per_page=100`: returned `[]`. This does not remove classic branch protection.
- `GET /actions/runners`: the available connector rejects this endpoint as unsupported. Organization runner inventory, capacity, groups and utilization remain `NOT_ACCESSIBLE` through this connection. Individual jobs do expose runner names and labels.

## Full pagination of the observed nonterminal backlog

The refreshed collection in `live-backlog-snapshot.json` retrieved queued pages 1–4, with page lengths 100, 100, 82 and 0. Every page reported total 282; the union contains 282 unique run IDs. These queued records were created between 2026-09-18 02:20:49 UTC and 2026-09-30 12:54:15 UTC. Pending, in-progress, waiting and requested collections were also queried: 1 pending, 25 in-progress, 0 waiting and 0 requested at capture.

Two old queue samples were inspected: queued run `36717833722` and pending run `36802271095` each returned zero jobs. The API records are evidence of a nonterminal backlog, not evidence of an available or saturated runner. The present connector cannot determine why those historical runs have no jobs. No job was cancelled or rerun during this investigation.

Latest global run-list page retrieved: 100 records, API total 40000. This count is recorded as the API response, not a verified lifetime run total. The full 40000-record historical collection was not fetched.

## Pinned candidates

| PR | Head at capture | Relevant observed status |
| --- | --- | --- |
| 2917 | `9a9e3b2e9dabd6957594861208b49f275f273e84` | Draft; own blocking run `39373679585` failed. Architecture `39373679417` succeeded. V8 was cancelled. Another PR used the same SHA; those runs must not be mistaken for independent qualification of this PR's base. |
| 2918 | `ca5b70d2684fb96063f5b70bb276525906dae7b6` | Draft; blocking `39300447616` failed; architecture and named Neuron qualification succeeded. |
| 2919 | `151a2c80f8fa549e5b7162eef3c846bf2fd90b5d` | Draft; blocking `39352639249` failed from native runner ENOSPC. |
| 2943 | `cff8d91ef68046327f492805193be8f69adfde8d` | Draft; blocking, architecture and multiple qualification workflows failed. |
| 2944 | `603238ba4721b2e9656c4647ce41c5f1664c1154` | Blocking `39496724981` failed; architecture succeeded; UI failed and V8 was cancelled. |
| 2945 | `719243606f6e718ac64b4e4b28a4b3cb4e337c23` | Draft; blocking and architecture failed; pre-coding readiness and repository integrity succeeded. |
| 2965 | `d18e1642a1ed4b7c6ba42571974b6a866436e0c8` | Draft; UI, blocking and architecture were still in progress at initial capture; V8 succeeded. |
| 2967 | `5d82db76436c10e684e03a0d215f19d6097b1478` | Draft; six-file terminal reconciliation change against main. Source review confirms it does not repair the separate cognitive schema SQLite connection or existing production writer test-helper Clippy failures. |

Inventory agent separately retrieved PR 2937 as **non-Draft**, head `b58d870a2c38ebee0aa0b974d9f03767c888fa7e`, mergeable state `blocked`. Its blocking and V8 runs below failed. A previous informal statement that this PR was Draft was corrected; use the inventory's live PR metadata.

## Root causes established from original job logs

| Candidate / run / job | Established failure | Status / next action |
| --- | --- | --- |
| #2944 / `39496724981` / `118912226488` | macOS Clippy rejects bare `SqlitePoolOptions::connect` in `hepta-memory/src/cognitive_schema_tests.rs:10` and roughly 16 `expect()` uses in ordinary helper functions within `production_writer.rs` tests. | Root agent implementing canonical connection and fallible helper repair. Preserve strict lint policy. |
| #2944 / `39496724981` / `118912168129` | Windows core-memory tests panic because `CARGO_BIN_EXE_codex-code-mode-host` is unset. | Audit Bazel binary/runtime-data resolution. Do not skip the affected tests. |
| #2944 / `39496724981` / `118912241314` | Windows core unit tests include `CARGO_BIN_EXE_codex` unset; Git wrapper children never publish PID/readiness; guardian committed snapshot and bounded fork assertions fail. | Separate binary lookup, process fixture readiness, and session ordering owners. Same Linux tests do not close native Windows failures. |
| #2944 / `39496724981` / `118912167995` | Windows security-related directory setup produces `PermissionDenied` across Hepta intelligence/AuthBus and other consumers. Sandbox helper executable resolution fails; capability write/delete tests and managed-proxy port assertions fail. | Needs native Windows investigation. Do not weaken directory or ACL enforcement to satisfy fixtures. |
| #2944 / `39496724981` / `118912168129` | Additional Windows failures include matrixd control socket not stale, core-plugins invalid-manifest metrics mismatch, and authorized-read RPC error code mismatch. | Distinct native/source failures remain; not all are infrastructure errors. |
| #2937 / `39490343769` / `118896513560` | macOS Clippy run reports remote-cache `No space left on device`; cache archive also fails to write with ENOSPC. | Reclaim within the owned runner job and bound output/cache duplication. Successful checkout does not qualify compilation. |
| #2937 / `39490343525` / `118869743561` | V8 Windows source checkout fails on repeated HTTP 503 from chromium.googlesource.com submodules, terminating before build. | External upstream transport failure. A successful metadata job does not qualify the V8 platform matrix. |
| #2919 / `39352639249` / `118400342228` | `rustc-LLVM ERROR: IO failure on output stream: No space left on device`; runner explicitly reports 0 MB. Compilation stops and nextest does not start. | ENOSPC remains a failed native run. Preserve original failed log; new successful execution is required. |
| #2945 / `39386823474` / `118508544531` | Inference-owner command exits 1; subsequent repository-control probe fails because write transport did not return explicit permission denial, so authorization remains unknown. | Qualification correctly fails closed; the observed transport result cannot be rewritten into permission-denied evidence. |

Cargo-deny jobs `118912167606` (#2944) and `118896512464` (#2937) are recorded as failed by the jobs API. The job-log connector repeatedly returned `Transport closed`; no specific advisory/root cause is asserted from those missing logs in this report.

## New execution-identity defect and validated repair

`scripts/hepta_ci_exec.py` at #2944 head `603238ba` called Git without `--no-replace-objects`. A real temporary repository demonstrated that `git replace` plus an index/worktree matching the replacement could leave ordinary status clean while testing different bytes under the original reported `tested_sha`. The unmodified executor dispatched the command and emitted `status=passed`. Replacement refs could also spoof merge parent order or change the independently recomputed merge tree.

The isolated repair is `/workspace/scratch/337c309bc660/hepta-ci-fix/replace-ref-identity.patch`, based on the exact #2944 source blobs. It adds `--no-replace-objects` to the common Git helper and four actual-repository regressions:

1. Different replacement source bytes reject before command dispatch.
2. A clean original checkout records its canonical tree/parents despite local replacement metadata.
3. Replacement parents cannot qualify an incorrectly ordered synthetic merge.
4. Replacement source history cannot change the independently recomputed merge tree.

All four regressions fail against the original helper. The corrected executor plus existing process-deadline suite passes **28/28**, with **0 skipped**. These are local Linux Git/process tests, not Windows/macOS or complete repository qualification. Existing workflow command tests deliberately use recording stand-ins for Cargo/just and are not represented as Rust compilation.

The final patch and hashes are in `hepta-ci-fix/validation.json`. After the successful suite, only two long assertion lines were wrapped; both changed Python files parsed successfully. The root agent owns final formatter validation, independent review, GitHub push, and the new exact-head required checks.

## Evidence files

- `failure-excerpts.json`: bounded original log context with job IDs, run IDs, line numbers and complete log hashes.
- `selected-job-counts.json`: complete job counts for the selected runs (all below one 100-job page). Counts include skipped and cancelled jobs separately.
- `live-backlog-snapshot.json`: all nonterminal status responses in the refreshed collection; explicitly non-atomic.
- `replace-regressions-red.log`, `replace-regressions-green.log`: actual local regression command output.
- `replace-ref-negative-control.json`: initial unpatched real-repository false-pass receipt.
- `EVIDENCE_MANIFEST.json`: hashes and sizes of original saved material.

No required gate, branch protection, security fence, scientific promotion state, runner job or external-effect permission was changed by this investigation.
