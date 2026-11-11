# MEM software composition: Git-object feasibility review

Status: the existing changes were combined without source edits in review PR #5935 at `2ae5215beaf8d7b7df111a090b82134beae2683d`. This is a read-only construction and publication proof, not a compilation or CI result. No host, native test, model request, Git commit, branch, or pull request was created by this review.

## Exact composition

The common commit is `96038ccf0660154fac143ba6cbe4be81e00813e8`, tree `1277666f3285cdf006d36478e6f74ddec38e1fe0`. The table is derived from original commit objects, GitHub compare metadata, and the actual directory-tree entries retained in `GIT_OBJECT_PROOF.json`.

| Component | Exact head | Root tree | Paths changed from common |
| --- | --- | --- | ---: |
| Owner G, including the earlier MEM owner, source freshness, and explicit-context profile stages | `9d9bdfbaeeec3c618f3fc80e2f663a29c13f4b27` | `07192603a5164f4b5d4da24e37595be2a0a04777` | 38 |
| Windows/Linux fixes | `cb0b276ffdb9852323cdd13ba9b4399b30ae0c37` | `61f266ce7f02e0c3b94c22871ebedcc72f28e456` | 7 |
| Ordinary-provider observation/retention, with those Windows/Linux fixes in its ancestry | `55951ed9094ae894f0256a3461fd9504ef060473` | `2ca6930d8abd148fe26fbe7d2857c760daa9316b` | 9 |
| Dependency, SQLx vendor, Matrix profile and RMCP compatibility | `f1fd544b3e12ed6aca83872cdeda8114a1e058c0` | `fff40d06312d4f6a185772cd8a62a618d55f31cf` | 65 |

Each comparison has the exact common commit as its merge base and has no commits behind that base. The Windows/Linux head is an actual ancestor of the provider head. Its seven changed paths have identical postimage blobs in the provider head. The 38 owner paths, 9 provider paths, and 65 dependency paths are mutually disjoint. There are no deletion, rename, or mode conflicts; all 112 overlay entries were read as mode `100644` from their original Git trees.

The original 73 directory-tree objects were rehashed using Git's binary tree encoding. Replaying each branch delta on the common root exactly reproduced all four published root trees. This checks the base, path, mode, and postimage mapping rather than relying only on a textual merge prediction.

The concrete Git API construction is:

- `base_tree`: `1277666f3285cdf006d36478e6f74ddec38e1fe0`.
- `tree`: the exact 112 entries in `GIT_TREE_PLAN.json`.
- Expected root tree: **`12159640adcf073b51f3837e75575e11f5c20233`**.
- Parents, in order: owner `9d9bdfbaeeec3c618f3fc80e2f663a29c13f4b27`, provider `55951ed9094ae894f0256a3461fd9504ef060473`, dependency `f1fd544b3e12ed6aca83872cdeda8114a1e058c0`.

The Windows/Linux lineage is already retained through the provider parent. Adding a fourth parent is unnecessary. Creating this review composition needs no new source, owner capability, provider admission, or external secret. Root independently recomputed these proofs and published the exact tree in PR #5935. A fresh read of the actual integration commit confirms the expected root tree and all three parents; its existing PR CI was observed scheduling against this head.

A narrower alternative omitting only the two ordinary-provider test files is also recorded in the plan: 110 paths, expected tree `9d65144eedc8d68cd32fd06ddf75e4dbcd151b69`, parents owner G, Windows/Linux cb0b, and dependency f1fd. The requested 112-path composition retains the existing observation work; this alternative is not a claim that it was published.

## Behavior carried by the two extra provider files

`codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs` adds phase receipts and stricter route/model checks to an explicitly ignored loopback provider smoke. Its final blob is `2d86359ec9e488369c47d182ac9d8fc273b9f675`. `codex-rs/hepta-agentd/tests/support/fleet.rs`, blob `169ccd842b31c9550cb000f520f8a6e66c5c5bb6`, retains a fixture root only when explicitly requested and keeps process cleanup enabled. Default tests retain their ordinary temporary-root cleanup.

Neither file enables a production model call by default. The G context-provider case is also ignored. The zero-model composition gate must preserve ignored-test selection and provider environment boundaries. It must not replay the original admitted provider turn or manufacture a new terminal for it. The original 20-second timeout and subsequently unresolved physical outcome remain separate evidence.

## Real remaining interaction risk

The disjoint source paths still share a dependency graph. The f1fd branch changes `libsqlite3-sys` from 0.37 to exact 0.39.1 and `rmcp` from exact 3.1.3 to exact 3.9.0. The Matrix vendor changes its `rusqlite` pin from 0.39.0 to 0.41.1; a local `sqlx-sqlite-0.9.0` vendor is introduced with compatibility and actual formatting changes. Cargo/Bazel compilation profiles optimize `matrix-sdk-store-encryption` 0.19.1 and `sha2` 0.11.1, while preserving the original Matrix test gate and cryptographic parameters.

Those changes can affect owner transaction settlement, canonical reads, import/revocation behavior, and other workspace consumers despite the absence of textual overlap. The combined head therefore needs actual execution of the relevant existing CI scopes. Previously qualified heads remain useful historical component evidence, but their results do not automatically qualify this new tree.

The original f1fd full RMCP evidence is now independently verified in `RMCP_FULL_INDEPENDENT_AUDIT.json`: all 268 raw PASS identities equal all 268 JUnit identities and the frozen original 268-case list, with zero failures, zero retries, the same run UUID, fresh timestamps within the original execution receipt, and seven unselected tests retained. The source and same-source CLI hash remain unchanged through the test and scoped-fix phases. This closes that exact Linux package execution subgate. It does not prove the new combined owner/MEM/dependency source or unexecuted platform consumers.

## CI boundary and runnable next action

The only workflow files changed by this composition are `.github/workflows/hepta-mem-python.yml` (blob `a1ecf3968b8d9bbc27099d792c12f1c5833b4e38`) and `.github/workflows/hepta-windows-private-state-native.yml` (blob `db54c8ce847d135a0213bd2e4a0a8858a32b2a51`). Other workflow bytes come from the common tree. A workflow's existence or a historically observed check is not itself proof that branch protection requires it.

The root `AGENTS.md` at common, blob `faa57cc0db48123e1011f1eb47692cd3bbbcfc3a`, requires repository `just test`, actual formatting, scoped fixes, dependency lock synchronization, and platform support appropriate to the changed code. It distinguishes focused changed-package validation from broader shared-component validation and does not require arbitrary `--all-features` expansion. The frozen `CI_REVIEW.md` and `CI_REQUIRED_MATRIX.json` now record the exact trigger, platform, feature and branch-rule analysis. The current common review base is unprotected with no required contexts; main's branch metadata names only `CI required` and `Architecture required`. The unchanged repository scope selector evaluates these 112 paths as `full_repo=true`, which selects the existing blocking fan-in, including its Bazel platform scopes. Those are existing workflow policies, not extra requirements invented by this review.

The remaining automatic action is concrete: continue the already-triggered applicable existing PR CI for exact head `2ae5215beaf8d7b7df111a090b82134beae2683d`, preserving real job identities, skips, failures, raw logs and artifacts. The initial 11 matching PR runs and 20 check records are a partial scheduling snapshot, not passing execution. Existing F2 controls should first be checked in combined-head Bazel evidence; only missing focused coverage should need an additional bounded invocation. Exact-head source verification precedes crediting a result. No original owner descriptor or model invocation is needed to create or run this software-only review composition. Unknown provider settlement, unseen-source capacity, original authority recovery, and scientific memory benefit remain outside these software CI results.

## Evidence files

- `GIT_TREE_PLAN.json`: 23,708 bytes; SHA256 `752ba348ffa7399ba74e5c20e29ceb153d0ec2cab7ba8aecc844275f3dd1c953`. Contains all 112 tree entries and both construction options.
- `GIT_OBJECT_PROOF.json`: 1,716,972 bytes; SHA256 `ccb155ac832be78df0a3a66270880a5f41aa054a68f35b628c3ed92bc4332afa`. Retains the original compare/commit/directory records and reconstruction proof.
- `RMCP_FULL_INDEPENDENT_AUDIT.json`: 5,128 bytes; SHA256 `7cec66427494da3711e928c3ade168a61592e09ab2809da87d9a29c00723e5d7`. Binds original raw log, JUnit, expected IDs, source, binary, and scoped-fix evidence; performs no new execution.

The frozen CI source review has 93 YAML workflows, their README and 13 supporting sources. `CI_REVIEW_FROZEN_FILES.json` binds its 121 files; `CI_REQUIRED_MATRIX.json` is 140,155 bytes, SHA256 `60a534369fcdb250abcab2d14b05e1ee73c7f3c4cd198d3dc9f512c5a2227ebe`. Both real-provider tests remain ignored under the observed zero-model command selections. The existing conditional CLA workflow may update PR metadata if its repository variable is enabled; the variable value was not accessible, so the review does not claim all automatic PR activity is read-only.
