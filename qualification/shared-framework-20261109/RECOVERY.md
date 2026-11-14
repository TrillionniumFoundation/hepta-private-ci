# Shared Cell framework recovery checkpoint — 2026-11-09

## Status: implementation delivery blocked by unavailable executor

This document preserves observations from the interrupted framework task. It is a recovery checkpoint, not a source-code delivery or a qualification pass. The complete candidate source, raw logs and audit files were still in the task workspace when the execution environment became unavailable around 13:31 UTC. The executor then reported no usable execution environment; a host-file upload also failed because no primary turn environment was available.

No candidate code tree, source branch, source PR or evidence archive had been uploaded before the outage. This checkpoint contains no recovered runtime implementation. The hashes below identify previously observed local objects; they cannot reconstruct the bytes. Workspace retention and the terminal state of the last static-check retry are currently unknown.

Full-library qualification remains **HOLD**. Production acceptance also remains **HOLD**.

## Frozen base and recovery coordinates

| Object | Exact recorded identity |
| --- | --- |
| Base commit | `e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5` (Root-learning evidence PR #5468) |
| Preceding code commit | `b443fe0cd7642316d016d78d6d3fbaa3e9dfc341` (PR #5467) |
| Baseline `codex-rs` tree | `4723e32b1130dddd340a8a1024c350e3855b820b` |
| Separately observed main | `732e934ba496d90fbe042b8d41d479ef901643e5` |
| Tested pre-maintenance source/CALLERS tree | `623767e430e269571482c9ae6ceb2e291ec53c91` |
| Candidate snapshot SHA-256, 33 files | `4eb3e881577d82fdc72d699a303419bd1bd58cc41ecbe73686440382b44f634f` |
| Frozen gate source-manifest SHA-256, 10,629 entries | `575e9fa0aa90582725ad1931974ebc3ca739b8e974edd3b31b13adb15cd9d490` |
| Candidate CALLERS file SHA-256 | `c93518ef759de4900ddf14e6cd27817a2bd8fbabcec4891a8703a3820316d0dc` |

These identities describe different scopes and are not interchangeable. The tested candidate tree is not known to exist on GitHub. Do not attach the observed test results to reconstructed code unless its exact source identity is independently established.

Last local task root: `/workspace/scratch/d037ec5d32c5`.

Important locations relative to that root:

- `native/`: candidate checkout on local branch `research/framework-d037-candidate`; HEAD remained the base commit.
- `validation/tested-sources/`: exact retained copies of the 33 tested candidate files.
- `validation/tested-candidate.json` and `validation/native-tests-4-source.json`: tested identity and full source inventory.
- `review-stages/20261109T124802339357Z-4eb3e881577d/manifest.json`: last complete pre-maintenance stage manifest.
- `review-stages/latest.json`: pointer to that completed staging run.
- `validation/`: raw logs, completed records, source inventories, JUnit and failure analysis.
- `native/qualification/shared-framework-20261109/README.md` and `VALIDATION.md`: locally prepared scope and validation documents; not uploaded.
- `root/pr_bodies_observed_draft.json`: nine source-PR drafts; not published.
- `run_gate.py`, `run_caller_gate.py`, `build_review_stages.py`, `capture_framework_maintenance.py`, `pack_framework_evidence.py`: local audit/packaging helpers.

## Observed implementation scope before the interruption

The seven responsibilities and heterogeneous execution direction were retained: frozen shared semantics/private heads, private temporal kernels, and deterministic authority/transactions/effect settlement. Simple diagonal SSM was explicitly not described as Mamba or S4D. HCSN remained a separate, unadmitted research candidate.

### Stateful backend

The candidate added `cell-diagonal-q24-temporal-v1`, a bounded Q24 diagonal recurrence through the original `CellGenerationWorkerV2`, inference control and generation journal. The checkpoint binds immutable loaded parameters, effective-model digest and event count. Same-model recovery restores exact state; changed parameters reject old state and require the original explicit Reset path. STOP preserves state and does not count as numerical forward use for the new profile.

A typed factory selects composed or diagonal Q24 from already opened files, with exact profile matching and no fallback. Ordinary Joint/V13 CLI selection was not wired to the new factory. General cross-model migration and Python-producer/native export parity remain open.

### Cross-Cell causal records

The candidate reconstructs original generation, source frontier, candidate/observation/definition digests, decision, checkpoint and computation outcome from original Cell/Circuit readbacks. It retains ledger claim/completion clock samples rather than retry time. It does not return raw inputs, equate separate clocks, manufacture external freshness, or treat a computation outcome as an ACT business outcome.

### Action realization and effective checking

The original goal-checked action driver gained advisory assessment and paired readback interfaces. Model/generation/source/checker/remediation/cost-unit pins and explicit time evidence are checked. Bounded integer conditional estimates use the exact criterion:

```text
r e s m L > r e s C_response + (1 - r e) f C_false_positive + C_check
```

Response cost applies even if remediation fails. Missing or unusable time remains Unknown; ACT errors, Partial and Unknown remain their original observations. This does not execute the checker/remediation, prove causation, calibrate a predictor, or change dispatch/settlement authority.

### Continued operation

Migration 0022 adds immutable retirement receipts to the original SQLite owner. Exact completed ACK identity moves from live outbox to retained history in one transaction. Retries retain identity; the 256 cap applies to live entries. Queue capacity is reserved before a new durable claim, and competing or failed claims release unused permits.

Retired history still grows. Claim-before-checkpoint crashes remain reconciliation cases. Automatic successor requests, multi-operation production registration, durable real training and a complete live seven-role loop remain open. The original Root assembly refusal and independent owners/attestations remain required.

## Completed behavioral evidence observed before maintenance

| Record | Actual result | Source unchanged during run |
| --- | --- | --- |
| `automation-tests-final` | Exit 0; 173 passed, 2 skipped, 13 binaries | Yes; frozen manifest above |
| `native-tests-4` | Exit 100; 859 run, 822 passed, 37 failed, 64 skipped | Yes; frozen manifest above |
| `framework-targeted-tests` | Exit 0; 79 passed, 844 filtered/skipped | Yes; frozen manifest above |
| `new-tests-results.json` | All 22 added tests matched passing JUnit cases in `native-tests-4` | Extraction from the same run, not a separate experiment |

All tests were invoked through the repository's `just test` recipe. The 22 additions comprise seven state/factory/NextUse tests, three causal tests, seven action-check tests, and five retirement/backpressure tests. Three existing tests were changed: live capacity reuse, closed-owner recovery, and legacy V1 migration teardown.

The two automation skips are existing parent-controlled ACT-1 child-worker entry points. No equivalent explanation is inferred for every skipped case in the combined library run. The 79-case selection overlaps the complete library run; counts must not be added as independent replications.

| Record | Raw log SHA-256 | JUnit SHA-256 |
| --- | --- | --- |
| `automation-tests-final` | `79fb722e5cb19957b7e299030d7fcec43d363a0772a19a9b1acfad30b3826281` | `0afd428bc2143d4453f15ff2f33ae4084a203913d834be05078e1e5e5136cecc` |
| `native-tests-4` | `74deaa7d452175ba5812aa0c6539a08c0b831d40bba6c2adc3c2487872c01d95` | `e029f5b86a84a42185f201051b1921deec2391e874a947ecbab26dd83160eda9` |
| `framework-targeted-tests` | `9da45eb82bcc8d7fb66120429b259b520a7a15dc820f26fdd4de1d4460561ff5` | `5070e55021649b321f1922a5245054212368650a6348353963cc9fda3d9aa1c7` |

These raw files are not included in this checkpoint. Their hashes were observed in completed gate records before the outage; they do not establish that the files remain retrievable.

## Failed cases and limits of the diagnosis

The 37 library failures comprised 32 EPERM-related cases and 5 cases where `cargo_bin()` could not resolve `hepta-joint-propose` from Cargo/nextest metadata. The 32 comprise three Python AF_UNIX creation failures followed by empty ready-line assertions, eight original control-socket probe failures, and 21 raw EPERM errors during socket/descriptor setup. Not every exact failing syscall was traced.

The 17 files containing failed tests and 20 directly related production/support files were compared with the baseline and found byte-identical. No baseline rerun was performed. This comparison does not establish an environment-only cause, exclude regressions elsewhere, or convert the failures into passes.

Three real-helper build attempts were retained:

| Record | Observed termination | Raw log SHA-256 |
| --- | --- | --- |
| `joint-helper-build` | Exit 101; `codex-core` rustc SIGKILL | `1b1a394c40cc6a100f103be5f233198b3551d9f30b73ea9a3fc9f9928f496a74` |
| `joint-helper-build-low-memory` | Exit 101; core compiled, then ENOSPC at hepta-authbus | `af4eee91694a6ae869c7f8c9050f0480fcec730575fe86b3584ccf08a4bcbf16` |
| `joint-helper-build-storage-recovered` | Cargo returned -9 at 13:16:22 UTC; no Rust diagnostic at log tail | `31a3516e4e35e05a3006b97eb434502036211d58744553f5963ef4c7cb16863f` |

No successful helper build or five-case replay was observed. The original 37 failures remain in the recorded combined result. SIGKILL alone does not identify the resource policy or prove OOM.

## Static checks and exact interruption boundary

The completed pre-maintenance full original caller verifier returned `PASS_HEPTA_CALLER_CLOSED_SET`: 6,158 Rust files, 180 boundaries/inventory entries and 169 protected-file rows, authorityGranted false. Its log SHA-256 was `3f7fef9a43af6dfd904965d0a1b3d9d1788da254d401c3ad8e455710cd884e3b`. This pass preceded later test-import fixes; it is not a final maintained-source scan.

Every original 179 boundary rows and 164 protected-file rows remained byte-identical. One retirement boundary and five protected-file rows were added. The local nine-stage builder checked each stage's original inventory/protected-file subset against that stage's exact Git blobs. It did not compile intermediate stages or perform a full caller scan for each stage.

The last complete pre-maintenance stage sizes were 355 / 265 / 275 / 176 / 368 / 346 / 162 / 286 / 191 changed lines. These are staging data, not published commits.

`scoped-fix` (`just fix -p codex-hepta-automation -p codex-hepta-agentd`) exited 101 with ENOSPC at 13:25:17 UTC. It recorded unchanged source manifest `575e9fa0...`; its log SHA-256 is `d34704c1dbf322e29c0954423ea9c57bc04acfd543ee14adcc1e05164b5cd9bf`.

`scoped-fix-no-incremental` then started with `CARGO_INCREMENTAL=0`. Its terminal result and any edits are **unobserved**. The exec-server disconnected and recovery timed out; the environment was then marked unavailable. Do not infer that this retry passed, failed cleanly, or left every source byte unchanged.

At interruption, `just fmt`, final maintenance capture, post-maintenance full caller verification, final stage regeneration, evidence packing and the nine-source-PR publication had not been observed as completed. No behavioral tests were run after maintenance began, following AGENTS.md.

## Runtime and auxiliary host observation

The observed local toolchain was Rust/Cargo 1.96.0, just 1.59.0 and cargo-nextest 0.9.151, with one Cargo job and dev/test debug information disabled. A task-local test profile set agentd incremental=false and codegen-units=1024; config SHA-256 `9e2fd04b460185f8f364132f4a4765b44d2142b14307f91e107b83b3e703851b`. Later helper attempts additionally overrode core's test incremental/codegen settings for that command only.

Completed task-owned compiler caches were reclaimed after resource failures. Source, test binaries, rmeta, proc-macro shared objects, native build inputs and logs were retained at the last observed cleanup. No other task's files or sandbox policy were modified.

The configured ROG host completed only a bounded read-only probe, job `1a1c066f067-5e21-a0c`, key `framework-d037-rog-validation-probe-v1`, exit 0. It reported x86_64, about 119 GiB total memory, cargo/rustc/just/git on PATH, and no nextest on that PATH. This did not copy the candidate source, verify Rust 1.96, run Unix socket gates, build, train, or create a remote candidate backup.

## Recovery sequence

1. Restore access to the same task workspace or recover its retained volume. Do not substitute baseline source or a model reconstruction for the missing candidate.
2. Read the terminal `scoped-fix-no-incremental` log/record and actual source bytes. If the process status is uncertain, reconcile it before starting competing maintenance.
3. Locate the exact tested-source backups and pre-maintenance manifest above. Verify their complete file hashes and candidate tree identity; distinguish any maintenance changes.
4. Finish the scoped maintenance required by AGENTS.md, run `just fmt`, capture the full before/after delta, and review any source changes. Keep the repository's no-behavioral-rerun-after-fix/fmt rule.
5. Run the unmodified final full caller verifier on stable maintained source. Rebuild the review stages from those exact bytes; verify guard staging and change-size limits.
6. Preserve every completed and failed gate, raw log, JUnit, source inventory, config and maintenance delta. Pack bounded evidence archives and run the repository blob-size policy.
7. Publish the actual source stack through the authorized GitHub connector, verifying returned tree identities. Bind results to the tested source and disclose the maintenance delta. This recovery-only PR is not that stack.
8. Resolve or separately qualify the failed complete-library cases on a suitable authorized environment. Keep production HOLD until original owners, independent evaluation/attestations and the real seven-role effect/observation/learning assembly exist.

If the original bytes cannot be recovered, reimplementation is new work with new identities and fresh applicable verification. It cannot inherit the old 22-test/79-test/173-test results.

## Separate research references

- [Stem-cell producer at the supplied reference](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4cc753af511bf7c406608caa9da0795d7691bd23/scripts/hepta_cells/README.md). It was not part of this baseline; no exporter parity was established.
- [HCSN development evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/bc75ed8ac158900449419052d9b8f6fcbe4912da/qualification/hcsn-localization-trainer-20261108/README.md). Five short fits shared seed 101; this task did not perform formal confirmation or admit HCSN as a mandatory shared base.
