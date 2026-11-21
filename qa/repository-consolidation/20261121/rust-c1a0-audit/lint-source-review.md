# Independent review: 8016166226cd6206ba09c83fa64acc91eca368ba

## Decision

**Static review accepted for the four-file test-only cleanup.** The candidate removes an unused test constructor, makes the existing readback verifier use the already compiled private checkpoint codec, and moves a last-used value instead of cloning it. It does not change a production checkpoint, journal, authority, persistence, serialization, or error-handling implementation. Runtime and strict-Clippy qualification remain to be obtained for the actual candidate source.

The reviewer read the four complete before/after files, their module declarations and re-exports, all direct verifier callers, the concrete freeze-plan/identifier/digest definitions, the repository instructions, and the original validation command records. The rejected d783273c proposal was neither read nor applied. No old owner job was queried, resumed, or replayed. No repository index, ref, or worktree source was changed.

## Exact source boundary

| Field | Independently verified value |
| --- | --- |
| Base commit | `6cbad406a4a203201edc0e103c1377d3664e3fbe` |
| Base tree | `08f5d464bedff1c1acbb3abe1d7f28e43827854f` |
| Candidate commit | `8016166226cd6206ba09c83fa64acc91eca368ba` |
| Candidate tree | `8616ba3b3667549340e0ec10eb15fc3df745ad3d` |
| Parent | Exactly the base commit, one parent |
| Complete tree | 59,349 leaves; 4 changed, 59,345 unchanged |
| Modes | All unchanged |

The base tree was reconstructed from the actual cloned Git tree. Overlaying only the four independently rehashed candidate blobs reproduces the candidate's complete tree. The recovered raw candidate commit was independently hashed to its claimed SHA. This establishes the complete source boundary, rather than merely checking a supplied patch description. See `INDEPENDENT-PROOF.json` and `SOURCE-INPUTS.json`.

## File-by-file findings

### 1. `learning_iteration_checkpoint.rs`

The removed `LearningIterationCheckpointOwnerV1::from_research_store` method is explicitly guarded by `#[cfg(test)]`. A whole-Rust-source symbol search at the exact base found one occurrence: its definition. There are no callers. The distinct `from_research_store_scoped_v2` constructor and its existing callers remain unchanged.

The only addition is a `#[cfg(test)]` child-module declaration for the existing readback support file. The enclosing checkpoint module is already guarded by `#[cfg(unix)]` in `lib.rs`, so this support is compiled only for Unix test builds. After removing the old test-only method and the new test-only module declaration, the entire remaining file is byte-identical.

In particular, `from_registered`, `from_registered_scoped_v2`, `restore`, `checkpoint`, `load`, snapshot decoding, CAS calls, record validation, and all existing error paths are unchanged. The source change does not implement a persistence repair.

### 2. `neuron_generation_learning_readback.rs`

The old `#[cfg(test)]` file-module declaration is replaced by a `#[cfg(test)]` re-export of `learning_iteration_checkpoint::generation_readback_test_support`. The enclosing `learning_readback` module is already Unix-only. All non-test bytes of this file are identical.

The established `learning_readback::test_support` path therefore remains available to the unchanged `neuron_generation_runtime` re-exports. There is no production API expansion and no new Windows reference to a Unix-only module.

### 3. `neuron_generation_learning_readback_test_support.rs`

The duplicate inclusion of `learning_iteration_checkpoint_codec.rs` and its `clippy::duplicate_mod` allowance are removed. The moved test helper imports `super::codec` from its new checkpoint parent. The codec's `pub(super)` functions are visible in this parent's descendant module. Its original error type and implementation remain unchanged.

The `AgentdGenerationLearningUseReadbackV1` import now resolves through the existing Unix-only crate re-export. Its concrete type is unchanged.

Both `verify_original_bytes` and `verify_completed_bytes`, including every statement and all 18 `assert_eq!` invocations, are byte-identical. Their source-output marker data, conditions, bounds, and `DENY_ALL`/historical-output checks are unchanged. The original codec and bundle-data modules contain no embedded test declarations, mutable static items, or module-path-dependent behavior; removing the duplicate module does not remove an embedded test suite or select a different encoder.

Direct verifier callers remain in:

- `neuron_generation_adopted_learning_tests.rs`;
- `neuron_generation_learning_runtime_tests.rs`;
- `neuron_generation_local_decision_tests.rs`.

The unchanged runtime re-export chain reaches all of them. Their test bodies are among the 59,345 unchanged leaves.

### 4. `circuit_model_selection_material_support_tests.rs`

Exactly one line changes: the final construction of `OriginalCellQ24MaterialReceiptConfigV1` moves `freeze_plan` rather than cloning it. The earlier clone passed by value to `read_current` remains. No later use of the local `freeze_plan` follows the changed line.

The concrete type is `DatasetFreezePlanV2`, with derived `Clone` and fields `StableId`, `Digest32`, and `Digest32`. `StableId` has derived `Clone` over `BoundedText<128>`, which has derived `Clone` over `String`; `Digest32` is `Copy`. No custom `Clone` or `Drop` implementation was found for these types. Moving the value preserves all fields and avoids one string allocation; there is no capability, lock guard, file handle, or custom destructor whose lifetime would be changed by eliminating the clone.

The file is compiled only through `runtime::tests -> circuit_task_ingress` (Linux-only) `-> q24_tests -> model_selection_owner -> original -> material`. It has no production inclusion. Its entire remaining content is byte-identical. Credentials, independent outcomes, request/budget values, original assertions, deadlines, and receipt operations are preserved.

## Meaningful validation to run on the candidate

No Rust compilation, runtime test, formatter, or Clippy command was executed by this reviewer. Static approval is not a claim that the remaining seven diagnostics have disappeared or that main is ready to merge.

Run the original affected-crate command, with the actual candidate's real helper executables available through the normal Cargo artifact mechanism, original default features, nextest profile, and deadlines:

```sh
just test -p codex-hepta-agentd --locked
```

This is the exact scoped command recorded in `HELPERS06-FINAL.json`; do not substitute a smaller test-name filter for that established crate run. Linux is needed to exercise both changes, since the material fixture is Linux-only. The existing Unix/macOS CI compilation remains useful for the shared-module visibility change. Windows alone cannot validate the changed Unix test helpers.

Check that the original retained/adopted readback, local-decision retention/adoption, positive model-selection/recovery tests are still enumerated and run. The codec's existing tests must also remain:

- `original_bundle_data_roundtrips_existing_checkpoint_shapes`;
- `original_bundle_data_rejects_wrong_framing_truncation_and_invalid_bundle`.

For the smallest strict lint check of the changed crate:

```sh
cargo +1.96.0 clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-agentd --all-targets -- -D warnings
```

The previously failing combined gate used the following exact command. Its result is needed before declaring that combined gate closed; reuse it instead of also doing the smaller check when the combined incremental run is practical:

```sh
cargo +1.96.0 clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-bellman-operator -p codex-hepta-agentd -p codex-hepta-shadow-qualification --all-targets -- -D warnings
```

The repository's existing B4 and caller checks remain applicable because the test module's physical owner changes. No new test or relaxed guard is proposed. Preserve the existing test-before-fix/format order and run the original final formatter. Existing main required checks remain separate from this four-file review.

## Evidence contents

- `before/` and `after/`: exact four-file inputs, rehashed against original Git blob identities;
- `support/`: immutable exact-base caller/module/type files used for review;
- `patch.diff`: the complete four-file patch;
- `CALLERS-*.txt`: exact-base symbol and module reference searches;
- `SOURCE-INPUTS.json`: file identities and hashes;
- `INDEPENDENT-PROOF.json`: raw-commit identity, full-tree reconstruction, unchanged-source and assertion comparisons.
