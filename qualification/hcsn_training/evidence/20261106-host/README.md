# HCSN host integration evidence

This evidence layer refers to implementation commit `fcffa43043ec7f36fa680c449c54b9b3446eb6a6` and tree `d0a50e37bda5073506734f0784807ba6f694d127`, delivered in [PR #4961](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4961). It does not change implementation files or move that CI head.

## Read first

- [status.json](status.json): observed results, retained failures, costs and open boundaries.
- [source.json](source.json): final formatted source hashes and exact Git identity.
- [stack.json](stack.json): eight reviewable Draft PRs and their commits.
- [manifest.json](manifest.json): byte counts, SHA256 and Git blob identities for every other file in this evidence layer.
- [repository-workflows.json](repository-workflows.json): dated overview of broader repository workflow states.
- [A bridge](bridge-a-result.json) and [B bridge](bridge-b-result.json): actual native supervisor, owner publication, cold recovery and second-block training.
- [native-scope.json](native-scope.json): original-workspace/lock provenance, 42+194 native passes and the parent-exercised ignored helper.
- [supervisor-audit.json](supervisor-audit.json): both lifecycle attempts, retained case stores and conservative UNKNOWN handling.
- [ci-observation.json](ci-observation.json): dated hosted state. Check its timestamp and terminal flag; local passes do not replace the final-commit hosted gate.

## Raw retained evidence

[raw-evidence.tar.gz](raw-evidence.tar.gz) contains 896 regular files: locally retained test/build attempts, six A/B bridge attempts, 22 real lifecycle case stores, baseline/source/runtime receipts, source patch, process/candidate bytes, independent review and read-only campaign observations. [raw-manifest.json](raw-manifest.json) identifies every member by bytes and SHA256. Two nonregular fault-injection nodes were recorded rather than read or archived.

Archive SHA256: `5414d5320c37ff9348e71ddebca1543c21f4fa0c056ae1537eb6a03207a1db2d`. Large reproducible native executables were removed after retaining their hashes and build identities; their inventories remain inside. Failed outputs and earlier observations remain intact; no failed output directory was reused.

## Scope

Each local change cycle ran its verification before `just fix` and `just fmt`, as required by AGENTS.md. Fix exited 0 without source changes and retained existing-file warnings. Formatting completed; tests were not repeated locally afterward. Hosted CI checks out the exact implementation SHA with the original lockfile, selects the actual Cargo target libraries, runs five Python suites without skips and retains complete or partial outputs.

Real signed SQLite integration uses a labelled supervisor double. The actual native-process fixture uses the real supervisor and worker. These must not be described as one tested signed-grant-to-real-worker path. Second training blocks restore the full published state and use independent SGD references; inference and training are explicit alternative branches from that anchor.

Candidates have synthetic fixture trust and DENY_ALL authority. Production registration, genuine trust/evaluation/adoption, physical energy, arbitrary-dt B refractory migration and scientific benefit remain outside these small fixtures. The original CUDA campaign, identities, budgets and failed B observation are preserved; no new CUDA task was started.

## Preserved hosted failure and fixture repair

The first hosted run on `92a8b4ac` passed the 194 neuron/owner tests, 40 Python tests and both A/B bridges, but full Automation had 118 passes and one existing V1 fixture failure. [ci-before-fixture-repair.tar.gz](ci-before-fixture-repair.tar.gz) retains its raw API/job/source evidence and all small artifact contents; its [manifest](ci-before-fixture-repair-manifest.json) also identifies the verified original ZIP wrapper. Every ZIP entry has a hash, including the four large executables that were not unpacked.

The repair changes only the V1 test fixture (+32 lines): remove post-V1 timer/dedupe objects in dependency order and assert the exact V1 catalog before the real SQLx upgrade. Its 18 integration tests passed; then the new change cycle completed fix/fmt without a subsequent local test rerun. [The patch](automation-v1-fixture-formatted.patch), [test log](automation-v1-fixture-repair-test-01.log), [verification](automation-v1-fixture-repair-verification.json) and [independent review](fixture-repair-review.json) are retained.

The latest [read-only CUDA observation](campaign-observation.json) and [original progress bytes](campaign-progress.json) supersede the earlier dated campaign snapshots in the local archive. They do not turn this engineering candidate into a science qualification.

## Final exact-head hosted result

[Run 42201095686](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42201095686) succeeded on `fcffa43043ec7f36fa680c449c54b9b3446eb6a6`; its job completed at 2026-11-06 10:28:02 UTC. The logs report **313 native passes** (194 neuron/owner + 119 Automation), **40 Python passes**, and both actual supervised A/B bridges including complete second-block recovery. The one direct-discovery helper is exercised by its passing parent. The repaired V1 fixture and signed TaskFlow DB integration both pass.

Read the [hosted summary](ci-final-summary.json), [hosted A result](ci-final-a-result.json), [hosted B result](ci-final-b-result.json), [raw small evidence](ci-final.tar.gz) and [member manifest](ci-final-manifest.json). Artifact 13495121785 was downloaded and verified at 108,165,145 bytes with SHA256 `45611d819dd2ecb6fa1a36a6fef9f17aa39de8fb3b018c1f082e6ab65c6e1d91`. Every ZIP entry is hashed; executable entries are represented by their verified hashes and build receipts. This is the HCSN engineering workflow result, not a claim that every broader repository workflow or the scientific campaign has finished.
