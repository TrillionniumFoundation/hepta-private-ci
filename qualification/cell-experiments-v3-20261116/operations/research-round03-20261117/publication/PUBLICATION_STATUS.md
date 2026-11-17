# Round03 publication status

The thirteen preceding stages have been published and individually read back as open, unmerged Draft PRs. This final stage adds the index and reproducibility inputs; its own final commit/ref/PR readback is recorded in the current Draft PR description to avoid a self-referential Git object.

## Verified prefix

| Stage | Draft PR | Change |
| ---: | --- | --- |
| 1 | [#6589](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6589) | Bind current-policy feedback and research identity |
| 2 | [#6590](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6590) | Train successive adapters from verified current weights |
| 3 | [#6591](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6591) | Verify current-policy rollout and warm-start behavior |
| 4 | [#6592](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6592) | Execute cells through one verified adapter pool |
| 5 | [#6593](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6593) | Preserve pool cleanup and cache failures |
| 6 | [#6594](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6594) | Execute message edges and Cell removal |
| 7 | [#6595](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6595) | Learn an A-only graph router with paid search |
| 8 | [#6596](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6596) | Bind common E2 initialization and Circuit execution |
| 9 | [#6597](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6597) | Freeze owned jobs and preserve incomplete reports |
| 10 | [#6598](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6598) | Account for search, ablation and missing costs |
| 11 | [#6599](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6599) | Retain source intake without inventing new samples |
| 12 | [#6600](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6600) | Preserve engineering observations and original failures |
| 13 | [#6601](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6601) | Document execution gates and unfinished E1-E6 evidence |

Verified prefix head: `eb56c51e4e73b0d466795b257a547ab93a0baa63`.
Verified prefix tree: `0161c5740c760b164ff938c02d0b26502e55cb7e`.

For every stage, the API-created tree matched an independently computed native Git tree. Commit parent/tree, exact branch head, Draft/open/unmerged state, base/head identities, added files, Git blob hashes and additions/deletions were read back. All paths are additions under the new online_v4 or Round03 evidence namespaces.

## Review the deliverables

- [Runbook](../README_ROUND03.md) describes the actual gates and commands. Its publication-pending sentence is an earlier timestamped documentation snapshot, superseded by this index and the final PR readback.
- [Operations status](../OPERATIONS_STATUS.json) binds source/evidence hashes and keeps runtime/qualification boundaries explicit.
- [Engineering evidence](../engineering/ENGINEERING_EVIDENCE.md) indexes the test observations, source history, failure records and explicit scripted fixtures.
- [Source intake](../data/SOURCE_INTAKE_03.md) and its archive preserve the absence of newly admitted independent trajectories.
- [Native calculation inputs](PUBLICATION_INPUTS_02.zip) and [native_tree.py](native_tree.py) reproduce the bounded-tree verification with local Git plumbing after remapping local input paths.

## What publication does not establish

The retained baseline is commit `43cc04442373a1ee7e8bad7942f329a1530b83dc`, tree `d97c1e1dab32817bad486cbe93eac027f59f6760`. Original core64 and previous experiment records were not modified. Native worktree creation timed out; host transport then became unavailable, so this publication used the authorized GitHub connector fallback. It is not a native push.

Engineering verification consists of 37 integrated CPU behavior tests plus one targeted report-reader regression, and one earlier real tiny CPU adapter warm-start test. Shared-pool tensor switching, the exact material backend smoke, formal prepare and new GPU experiments remain NOT_RUN. No new independent samples, external teachers, users, C tasks, production adoption or PoUW eligibility were created.

The current just fmt request has no execution receipt because host transport returns HTTP404/tunnel_client_not_seen. No complete CI-green or merge claim is made. The final PR records the exact-head CI observation available at publication time.
