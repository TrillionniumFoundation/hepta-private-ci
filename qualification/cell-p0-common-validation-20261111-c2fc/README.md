# Common Cell candidate: exact-source validation evidence

## Identity and decision

The tested source is **`1e822b3aeac79d9e9fc169f7fc6a48821baa6654`**, tree **`80f33dcd59cf3721dbec3a9cb2ee695db5187cd5`**, in [PR #5890](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5890).

This directory is published on a separate evidence branch. The commit containing this directory is **not** the tested source. Publishing evidence does not move the candidate branch or transfer qualification to a new commit, even when production source bytes are unchanged.

**Result: source and research engineering gates PASS; native qualification remains pending; P0/P1 adoption remains HOLD.** No complete production A -> learning -> independent B -> C -> daemon/Root cold-recovery chain or new independent real confirmation is established here. P2-P4 advancement is not admitted.

## Observed validation

| Check | Actual result on the tested source |
|---|---|
| Learning, Q24, NoUpdate source closure plus CALLERS mutation cases | **134 distinct cases PASS**: 69 closure + 65 CALLERS; zero failures, errors or skips |
| Five research gate modules | **76 distinct cases PASS**; zero failures, errors or skips |
| Full CALLERS scan | **PASS_HEPTA_CALLER_CLOSED_SET**; 6,298 Rust files, 213 boundaries and inventory entries; 215 protected rows across 171 distinct protected paths; `authorityGranted=false` |
| Source identity | Clean before/after; all 14,431 Git tree/index entries unchanged; all 6,683 scanned/imported source inputs match their Git blob and SHA-256 |
| Two git-attribution native cases, local | **NOT_RUN_RESOURCE_PREFLIGHT**; zero test starts, no cargo/nextest invocation, no execution record or JUnit fabricated |
| Final repository formatting | **PASS_FORMAT_NO_CHANGE**; `just fmt --base a15acbf4db6178523a9297033c86e3be0b2725a3`, exit 0, zero changed bytes; no behavior test repeated afterward |

The independent native preflight also hashed all 14,431 tracked physical files (215,794,431 bytes), with equal before/after inventories. These checks bind their recorded intervals; they do not substitute for a native run.

All old 133 source case identities are retained. One canonical original-owner-key case was added and none removed. The comparison establishes case identity retention, not unchanged test bodies. The original 9821 assembly's one failure event and 14 error events across five cases, its cancelled full scan, and c36's interrupted precheck with tests NOT_RUN remain preserved. No earlier result is relabelled as a pass on S.

## Hosted snapshot

Observed through **2026-11-11 01:33:33 UTC**. All five run-level and ten observed job-level head SHAs match S. Initial and second snapshots, R history, and the third final snapshot remain separately retained.

| Workflow | Observed state |
|---|---|
| [Hepta daemon learning native](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937682992) | `in_progress` |
| [blocking-ci](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937683233) | `queued` |
| [Hepta architecture convergence](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937682929) | `queued` |
| [Hepta Cell research stage evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937683069) | `success` |
| [v8-canary](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42937683149) | `success` |

The native helper build completed successfully. Its combined **Run ordinary and Root suites then scoped maintenance** step is in progress. Step metadata cannot determine individual ordinary-test or Root execution, completion, counts or pass status; those remain unknown. The workflow contains the three full library packages and seven exact Root parent requirements. Full native qualification has not been observed.

Research workflow success is directly bound to S. Hosted success logs were not read for test counts, so the local 134/76 counts are not attributed to hosted execution. The v8 metadata workflow succeeded with both build jobs skipped; this is not a V8 build-pass claim. Architecture source-head/base-merge and blocking scope/blob jobs remain queued at this snapshot; Codespell succeeded.

## Source binding and included repairs

The inherited same-source execution recorder requires canonical 40-character source/tested SHAs, a matching clean HEAD and an explicit lane. The source lane requires equal source/tested SHAs; the merge lane checks exact ordered parents and the independently recomputed merge tree. It rejects missing identity before dispatch and changes observed during execution. The local native recorder was planned but not invoked after the resource preflight refused to start a fresh build. See `raw/assembly/SOURCE_BINDING_REVIEW.json` in the archive for the read-only code audit.

The candidate combines the published ordinary Q24, original recovery, native-maintenance, RMCP and output-transcript histories. It integrates [#5867](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5867), where incomplete cost coverage keeps totals unknown and reports recorded partial subtotals separately, and [#5877](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5877), where the legal 600 ms auth-refresh response is exercised under the unchanged production five-second deadline. Precise diagnostics, the current authentication generation and the exact three-request expectation are retained.

Before any tests on S, the published `a15acbf` exhaustive-match compile repair was incorporated. `TrainingNoUpdateV2` remains rejected as a completed generation use; no NextUse or FinalUse is created by training without a candidate.

## Adoption and statistical limits

Production Model Proposal/profile, original stage-owner enrollment, original runtime identities, independent B custody, matched baseline histories and full product recovery are not established. Test-only research proposals and unpublished material-owner drafts grant no authority. A research decision to retain the baseline is not evidence that the complete production NoUpdate/recovery path has been accepted.

The fixed-source [P1 adoption matrix](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/1e822b3aeac79d9e9fc169f7fc6a48821baa6654/qualification/cell-p0-common-20261111-c2fc) retains task/source/seed/fit distinctions. MEM selector and memory retention remain separate; [#5872](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5872) is one synthetic 4,096-record capacity run with zero new real confirmations. CTRL's uncertain dispatch remains UNKNOWN. PERC has a synthetic actual-encoder comparison, ACT episode repeats are not new tasks, VERIFY engineering tests are not independent policy confirmations, and PRED's 189 fits remain development execution.

## Recorded costs

| Local subprocess | Wall seconds | CPU user seconds | CPU system seconds |
|---|---:|---:|---:|
| source-unittest | 28.524822 | 12.841798 | 2.378711 |
| research-unittest | 57.183447 | 11.265446 | 15.701532 |
| callers-verify | 781.580629 | 665.248045 | 13.284968 |

These three subprocesses ran concurrently; their wall times are not summed into elapsed campaign time. Per-process high-water RSS is recorded separately and is not a summed concurrent-memory measure. The native inventory/report interval was 53.537296 seconds; earlier preflight time is unknown. Formatting took 0.398799 seconds. Native compile/test time was not measured because those local commands never started. Hosted compute, communications and complete campaign cost remain unknown.

## Files and raw evidence

- `CANDIDATE.json`: exact source identity and adoption boundary.
- `SUMMARY.json`: component outcomes, unknowns and cost limits.
- `SOURCE_GUARDS.json`: actual case counts, commands, process costs and scan receipt.
- `NATIVE_PREFLIGHT.json`: the explicit local non-execution result.
- `MAINTENANCE.json`: final formatting and unchanged identity.
- `CI_SNAPSHOT.json`: latest fixed hosted run/job observation with earlier snapshots retained in the archive.
- `RAW_MANIFEST.json`: every raw file's path, byte count and SHA-256.
- `raw-evidence.tar.xz`: 112 raw files, 19,607,272 original bytes, stored losslessly; raw source inventories, commands, logs, receipts, case comparisons, three CI snapshots and provenance are included.
- `PACKAGE_MANIFEST.json`: byte/Git-object/SHA-256 identities of the delivered package files, excluding the manifest itself.

Archive SHA-256: `1f908b1e8c63ea97eb3175853e3f362fb9550f44214820c45738788d80903305`.

The original failed assembly remains linked from the [candidate evidence directory](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/1e822b3aeac79d9e9fc169f7fc6a48821baa6654/qualification/cell-p0-common-20261111-c2fc); those raw failures are not replaced by this result.
