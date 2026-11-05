# B16 V6: current-host build-only cache provenance

This is a disabled, source-only runner candidate. It neither starts B16 nor changes a native checkout, a ref, a test, a retry count, or a budget.

The existing `reuse_final_A` path continues to consume the reviewed historical A artifact receipt. The new `BUILD_ONLY_CURRENT_HOST` path consumes a separate, pinned P4 receipt for the newly built cache. Historical A evidence remains at its real source revision and retains its original internal ROG paths. A byte-identical archived copy can be transported as evidence; its contents are not rewritten into current-host artifact identities.

## Required new input

`foundation-build-only-binding-UNBOUND.json` contains no enabled execution guard or invented P4 hash. Before a future binding can be enabled, the actual P4 receipt must provide:

- The current host alias, full uname, uid and effective uid, cache owner, source directory, target directory, code commit, tree, ordinary index, both locks, pinned tools, original recipe identities, and controlled environment.
- The three original successful commands: the normal six-helper build, full locked Cargo metadata, and full unfiltered nextest catalog. Complete stdout and stderr are pinned. P4 runs no tests.
- The six actual source guards around those commands. The loader reads the existing bootstrap fields `head`, `head_tree`, `working_tree`, `ordinary_index`, `guarded_files`, and `untracked`.
- All 363 catalog program roles and 33 helpers, with actual files, sizes and hashes. The six initial helper identities and their separately observed identities after catalog compilation remain separate; feature unification is not relabeled as byte stability.
- `role=BUILD_ONLY_CURRENT_HOST`, `tests_executed=false`, and `test_qualification=false`. A build-only receipt is rejected if substituted for historical tested-A evidence.

The complete current metadata must describe the same source and target, all 193 original workspace members and 1,501 resolved nodes. At the foundation entry, it must match that epoch's actual metadata. The catalog must be unfiltered and its complete program roles must match the historical A role roster; actual host-dependent paths and package identifiers come from the new raw catalog. Each original foundation phase still rebuilds its helpers and catalog and verifies the current metadata, paths, features, program identities, helper identities and fresh JUnit through the unchanged native runner.

## Cache lifetime and later epochs

Before the first foundation source change, V6 rehashes every current build-only program and helper and checks that it is executable under the approved target. This is a current-host cache observation, not an A test result. Later epochs retain the immutable P4 build receipt as provenance, while their actual current outputs are obtained by the existing per-phase builds and catalogs. They do not compare rebuilt binaries to the old P4 hashes. Epoch continuation binds the same mode, host, owner and baseline receipt in addition to all existing source, lock, index, graph and prior-qualification checks.

The existing frozen family file remains byte-identical. For the new mode, the loader derives an explicitly build-only family from the pinned current metadata and catalog. Only the reviewed foundation source frontier and operation order are inherited from the frozen family. Its historical last-tested fields do not become labels for the new build cache.

The capacity calculation and limits remain unchanged: the foundation-only conditional allowance is 12,000,000,000 bytes for temporary Cargo growth, 2,000,000,000 for evidence and 8,000,000,000 reserve. Other epochs retain their original budget rules. Fresh free-space checks remain mandatory. Neither a successful cold build nor these file identities proves a compiler peak or authorizes cache deletion.

## Verification and remaining gates

Four small cloud-only controls cover wrong host/source, a missing physical artifact, build-only evidence disguised as tested evidence or a failed build, and preservation of the old family with a separately labeled new family. Their artifacts are tiny synthetic files, never executed as programs. An isolated Git application reconstructs all 28 candidate files exactly.

The full source payload, five epoch manifests, native command and JUnit code, physical oracle code, lock-generation code, all negative restoration bodies, and source-application guard bodies remain byte-identical to V5. Only the cache provenance branch, its continuation receipt, disabled templates, integrity list and four guard controls change.

Actual P4 receipt validation, the bound launcher, fresh native prerequisites, root execution approval, all foundation tests and counterfactuals, later lock generation and the remaining B16 qualification are pending. Internal stage labels are `B16/phase`; they do not change the original blocker ledger.
