# Exact composition: existing CI and automatic-event review

This review covers commit `2ae5215beaf8d7b7df111a090b82134beae2683d`, tree `12159640adcf073b51f3837e75575e11f5c20233`, and the 112 paths in `GIT_TREE_PLAN.json`. Its branch is `codex/mem8-integrated-source-20261111-ed353817`; draft PR [#5935](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5935) targets `codex/mem8-common-source-20261111-ed353817` at `96038ccf0660154fac143ba6cbe4be81e00813e8`.

The work here is read-only GitHub retrieval and local parsing of pinned source. This reviewer launched no host job, native test, model request, dispatch, rerun, cancellation, or ref mutation. The parent's separately authorized PR creation produced the actual runs listed below. Earlier native results on 66f, F2, G, provider or dependency heads do not become results for this combined head.

## Automatic events and the two real-provider tests

All **93 YAML workflows plus their README** were read from pinned Git blobs. The only composition workflow overrides are MEM `a1ecf3968b8d9bbc27099d792c12f1c5833b4e38` and Windows private-state `db54c8ce847d135a0213bd2e4a0a8858a32b2a51`; the remaining files inherit common96038. Complete contents and hashes are in `WORKFLOW_SOURCE_CAPSULE.json`.

For the actual new branch and 112 changed paths, the event audit finds **zero matching push workflows, 11 matching pull_request workflows, and one conditional pull_request_target workflow**. No workflow has a `create` or `workflow_run` trigger. Release, package publication and deployment workflows require separate tags, named integration branches or manual events that this branch/PR creation does not supply. In particular, this branch does not contain `full-ci`, so it does not automatically start `rust-ci-full`.

The ordinary provider case `real_agentd_loopback_provider_read_only_smoke` remains `#[ignore]` in blob `2d86359ec9e488369c47d182ac9d8fc273b9f675`. G's `episodic_real_provider_fresh_context_smoke` remains `#[ignore]` in blob `aa0e8fd90b112fe0a4f5eab18bf5dacb76d3a8a7`. The matching MEM, Windows and architecture commands do not enable these ignored cases. `just test` calls the unchanged nextest wrapper, which does not inject `--run-ignored`; the Agentd Bazel declaration supplies no extra unit/integration test arguments, and the macro defaults are empty. The architecture workflow's one explicit `--ignored` invocation names a bounded history/scale test in **codex-hepta-infer-core**, so it does not select either Agentd provider test. This is a source-selection finding, not a measured physical-request count for pending jobs.

There is one existing write-capable exception to any claim of entirely side-effect-free PR automation: `cla.yml` uses `pull_request_target` and the guard `vars.ENABLE_UPSTREAM_AUTOMATION == 'true'`. If enabled, its pinned CLA action can update statuses, PR metadata and `cla-signatures`. The connector rejected the repository-variable endpoint, so the guard value is unobserved. This is neither a model request nor a release/deployment job. Normal CI also writes runner-local fixtures, caches, logs and artifacts. Lock-proposal jobs intentionally generate review postimages inside their ephemeral checkouts; none pushes those postimages to a source ref.

## Actual branch requirements

The read-only branch endpoint returned these current settings:

| Target | Protected | Required check contexts from branch metadata |
|---|---:|---|
| common96038 review base | No | Empty list; enforcement off |
| main | Yes | `CI required`, `Architecture required`; GitHub Actions app 15368; enforcement `non_admins` |

The repository rulesets endpoint returned `[]`. The more detailed classic protection endpoint returned 403 to this integration. The valid branch metadata above supports the named contexts; it does not support a claim that every other administrative protection is absent. Source/response records are in `CI_BRANCH_RULES_READONLY.json`.

The current review PR does not target main. Its CI jobs still execute and are relevant software evidence; they are not all separate branch-protection requirements. The two named main contexts are workflow fan-in jobs with explicit dependency rules.

### `CI required`

The exact `scripts/hepta_ci_scope.py` pure function was evaluated locally on the 112 pinned paths. It returned all five architecture groups, `native=true`, `derived=true`, and **`full_repo=true`**. Cargo workspace manifest/lock changes and workflow changes already select this path in the repository. This is the existing repository policy, not a newly imposed all-platform rule.

For this result, `blocking-ci.yml` requires successful `scope`, contract gate, Bazel, blob-size policy, cargo-deny, codespell, repo-checks, rust-ci, and SDK. Its existing fan-in allows only `hepta-scoped` and `lightweight` to be skipped for this full-repository path. A failed scope selection must not be mistaken for permission to skip downstream jobs.

| Existing dependency | Concrete execution scope | Existing job budget |
|---|---|---:|
| Contract gate | Canonical document/readiness checks and source identity | 15 min |
| Bazel tests | macOS ARM64, macOS x64, Linux x64 GNU and musl; Windows x64 in four existing shards | 120 min per test job |
| Bazel Clippy / release-build verification | Linux x64, macOS ARM64, Windows x64 | 120 min per job |
| Blob policy / cargo-deny / codespell | Existing blob, RustSec/advisory/license and spelling controls | 30 min each |
| Repo checks | Repository checks; Hepta path tests on Linux, Windows and macOS | 10 min repository; 20 min per native-path job |
| Rust CI | Manifest graph, locked metadata, Rustfmt, benchmark smoke and cargo-shear; conditional lint-package checks | 15–30 min per job |
| SDK | Python SDK tests; Bazel-built CLI/code-mode host and TypeScript SDK tests | 20 min / 60 min |

The extra Bazel native-Windows-on-main job is guarded by `push && refs/heads/main` and is not applicable to this PR. Release-build verification compiles artifacts; it does not publish a release. `rust-ci-full` is a separate manual/full-ci-branch/postmerge matrix, not a missing automatic requirement for this branch.

### `Architecture required`

The existing architecture job has `source-head` and `base-merge` lanes on `ubuntu-24.04-arm`, each with a 60-minute budget; the aggregate job has 5 minutes. This diff selects inference, effects, lifecycle, objective and learning. Existing commands cover inference/type contracts and the bounded history measurement; operations and recovery; lifecycle/migration/topology; objective/prompt policy; final-use/browser semantics; selected-artifact adoption, ledger and selector isolation; compiled runtime tasks and restart fixtures. These are repository test fixtures, not recovery of an authenticated original production owner.

The candidate-tree gate can reuse source-head native work when the separately identified merge tree is identical. That is an existing policy with source/merge records and the aggregate success check, not permission to transfer old-head native results. Both lane outcomes must be inspected before treating `Architecture required` as successful.

## Other actual PR workflows

These workflows match the path/base filters but are not separately listed in main's two required contexts. They still produce useful evidence and failures must be reported accurately.

| Workflow | Existing scope | Budget / current trigger observation |
|---|---|---|
| MEM candidate and replay controls | Two Python contract jobs; exact-source CLI build/binary binding, memory `episodic`, Agentd `episodic`, protocol, scoped fixes | 8 / 120 / 20 min; all three jobs queued in initial observation |
| Windows private-state native | Path ACL/reparse/hardlink tests, Prompt Registry, final-use/authority stores, Agentd prompt runtime, the exact signed-credit rejection case | 65 min; queued |
| Windows original CI regressions | The committed `.github/fixtures/windows-current-ci-scope.json` list through its strict runner; original process/transport/backend cases and built sandbox helpers | 65 min; queued |
| UI product foundation | Source-head/base-merge browser-renderer checks, native-presentation feature tests and an artifact-only Bazel lock proposal | 60 / 45 / 60 min; queued |
| V8 canary | Metadata always; changed `MODULE.bazel`, lock and workspace manifest select the existing GNU/musl/macOS release+sandbox matrix | 90 min metadata; 180 min per selected build |
| Bazel stable-lock proposal | Runs original lock-update/check twice, preserves postimage and patch for review | 30 min; queued; a generated proposal is not an accepted source change |
| Keyring lock proposal | Re-resolves keyring, preserves Cargo.lock postimage/patch and a non-gating advisory probe | 30 min; queued; it may fail when no proposed diff exists; it is not the required cargo-deny job |
| App-server schema refresh | Exact old branch-name guard | Actual `skipped`; not a missing job to force |
| Production HOS2 proposal | Exact old branch-name guard | Actual `skipped`; not a missing job to force |

V8's Windows source-build submatrix is narrower: it depends on listed V8 infrastructure paths or a resolved V8 version change. Its metadata output, rather than the generic Cargo.lock path alone, decides those Windows jobs. The machine matrix retains the full conditions and targets.

The MEM native job's `minimum-tests=1` is a nonempty-execution check. Final evidence must still audit the actual **11 memory case identities, six nonignored Agentd identities and commit/revoke/panic child markers**, plus the complete protocol receipt. These counts describe unchanged source cases present in the composition, not completed runs on 2ae. The new G provider case must remain unselected. A compile error, formatter/fix rewrite, or zero-case execution must remain a failure with its raw evidence.

## Concrete bounded route and any residual coverage

The ordinary PR route is already working: all 11 expected PR workflows appeared for exact head2ae. No manual event is needed to overcome draft status, paths or the common base. The initial records are in `CI5935_INITIAL_OBSERVATION.json`; subsequent observations are separate snapshots. At that first observation nine workflows were queued/running and the two branch-specific jobs were skipped. No terminal native PASS is claimed there.

Continue the existing runs without cancel/rerun. Retain artifacts and associate each receipt with its actual head/tree, source/merge lane, command, tool versions and final source/binary hashes. Required fan-in results must be evaluated together with their underlying jobs; empty combined commit-status arrays are not evidence that check-runs passed or were absent.

For focused MEM composition coverage, the existing native-owner job supplies the first bounded route. Its current registered workflow is **412048854**, run **42971470585**, native job **130360698762**. The current blocking run is **42971470498** and architecture run is **42971470237**. No run was dispatched by this audit.

Existing F2 controls outside the MEM job's direct command list should be checked in the new combined-head Bazel results before arranging any additional execution. If their raw evidence is absent, the prior F2 driver already supplies narrow commands for app-server's two `required_*` feature-constraint cases, Agentd's `episodic_embedding_keeps_the_store_but_removes_implicit_memory_paths` with `qualification-cognitive-write`, `codex-hepta-memory-extension`'s disabled-memory-extension control, and `codex-core`'s empty native inference router. Exact historical argv and case names are preserved in `CI_EXISTING_F2_CONTROLS.json`. Reuse those flags on the new source; do not broaden into all-features or inherit the F2 result. Those are existing feature controls, not requirements for running either real-provider smoke.

Manual routes are available only as a deliberate later action, not a reason to duplicate these active runs. Architecture and rust-ci declare `workflow_dispatch` and their files exist on pinned default-main. MEM and both Windows workflows declare dispatch on the candidate and have registered IDs from real PR runs, while their files are absent from that pinned default-main inventory. The GitHub API accepts a workflow identity plus a branch ref for dispatch; this audit did not attempt a POST or establish an acceptance receipt. GitHub's current documentation distinguishes default-branch UI registration from API/CLI dispatch against another ref after registration. If later needed, the concrete request form is `POST /repos/TrillionniumFoundation/hepta-private-ci/actions/workflows/<registered-id>/dispatches` with JSON `{"ref":"codex/mem8-integrated-source-20261111-ed353817"}`; record the actual resolved SHA before treating it as a run. See [GitHub workflow_dispatch documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch).

## Limits preserved

- The unknown original provider turn is not retried or reclassified. Its physical provider-request count remains unknown.
- Readiness of a current route, a zero-model native test, and original owner/effect recovery remain different facts.
- The source exclusion ledger's 69 known groups and 16 candidate upper-bound groups are not verified unseen capacity or memory benefit.
- Existing Fence, security, permissions, test assertions and whole-repository checks remain unchanged.
- This audit's source/trigger review is complete. The new composition's execution result remains determined by its actual CI receipts.

## Evidence index

`CI_REQUIRED_MATRIX.json` contains exact matching/nonmatching events, job conditions, platforms, matrices, features, budgets, reusable calls, branch-protection interpretation and dispatch declarations. `WORKFLOW_SOURCE_CAPSULE.json`, `CI_SUPPORTING_SOURCE_CAPSULE.json`, `CI_WINDOWS_SCOPE_SOURCE.json` and `CI_IGNORED_G_SOURCE.json` retain full pinned sources; `ci-source/` contains identical materializations. `CI_MAIN_WORKFLOW_INVENTORY.json` and `CI_MAIN_DISPATCH_SOURCES.json` retain the default-main registration check. `CI_BRANCH_RULES_READONLY.json` retains successful branch reads and the rejected administration/variable endpoints. Derived `__pycache__` files are excluded from the review package.
