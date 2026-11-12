# Fixed three-way integration for PR #6213

## Immutable source identities

- Common ancestor: `a96d1b821d10ed3d9e99dd06c5141f9f242ae318`.
- Existing PR head: `872b1b68342285893abd4c09f9141bcc19d8f9ce`, tree `5a22d17b8d21f2b9843d508ec4ef21f8045a0c66`.
- Fixed observed upstream: `d3977d9a1bed3e89952c576c45660b04ea674faf`, tree `57558558841da4a3209164d0033b903a553205d6`.
- Complete candidate tree: `e72ab40aadbfd3f69b3b272f1597ccaeb39fe75b`.
- Proposed merge parents, if the root agent publishes after review: existing PR head, then fixed upstream. This review created no commit, ref, PR or run.

## Scope and resolutions

The ancestor comparisons contain 151 paths on our side and 140 upstream, with 31 overlapping paths. The candidate starts from the complete upstream tree, retains all 120 nonoverlapping ours paths, and supplies 39 explicit resolution/interface-adaptation entries. The 159 overlays comprise 13 production files, 16 QA files, eight fixture files, two manifests and the 120 unchanged ours-only files. Actual Git-tree comparison found 158 changed leaves: the completion-readiness fixture intentionally equals the complete upstream version. No unlisted leaf changed, no leaf was deleted, and all 151 existing ours input modes plus eight upstream-only adaptation modes remain 100644.

1. **Original Candidate lanes and upstream evaluated retention.** The upstream four/five/six-cut routing, full opaque post-Evaluation originals, same original channels, Root gates and physical before/after reads remain. Our unique owning ResidentLane replaces the old borrowed Mutex guard in construction and read paths. Five additional upstream-only retention files required the same interface adaptation because the original common continuation already uses ResidentLane. Eleven old lock calls in the 110 upstream added/modified Rust files become try_take/state_mut; the original failed/requested flags, successful clear point, errors, I/O order, 128-frame limits and timeouts remain. No client is cloned or new channel created by this adaptation.

2. **Physical CURRENT read service.** The complete ours same-call NextUse ReadSet and final actual Source/CURRENT checks are retained. Upstream adds its evaluated-readiness child and strict evaluated four-cut retained Version channel entry. The original legacy channel still calls legacy()? and admits Selection only. The other overlapping read-profile/capability files preserve upstream new APIs and our cfg(test) coverage hooks.

3. **Evidence timing diagnostics.** The original callback and 128-frame loop retain their non-test behavior. The upstream cfg(test) stage/timing API coexists with our original-response wrapper. A test-only per-exchange Drop guard flushes the fixed eight-slot thread-local event buffer only after exchange returns, including error and EOF. Callback events do not emit stderr or log payload/signature bytes. The support definition and production call site were independently read and match.

4. **Fixtures.** The boxed original Panel/Member/Host/Publication chain and real original peer cleanup remain, including upstream before_publication returning the corresponding boxed Host. The original three independent C fault cases remain separate tests, and all original error, byte, count and publication assertions remain. The new upstream bridge/read-transaction module registrations remain. Readiness explicitly preserves the upstream profile-aware fixture, which includes the legacy rejection required by our prior fix.

5. **Exact caller inventory and source guards.** CALLERS contains 608 boundary records, 426 protection records over 352 distinct paths. The final 15 changed caller lists follow the exact source-reviewed tuple manifest. Nine protection blocks combine the actual lease/read-set postimages with upstream guards. The active blob allowlist has one current CALLERS pin: SHA256 `03df70c12e195c96d09423e8bfa2b52c321520918ba4fea8c88eaff758ca0b63`. Historical conflicting pins remain history, not active allowances. No checker, exemption, role or authority is added.

6. **QA migration.** All methods from both versions of the 13 overlapping QA files remain, including our two added refusal methods and upstream two added methods. Three additional upstream-only QA files required exact marker/tuple synchronization: three lease-expression markers, two retention-command caller tuples, and three evaluated-Version tuples. The latter five updates append the actual existing ours caller paths to the complete upstream lists. Across all 58 fixed-directory source_closure.py inputs, a restricted static parser checked 39 literal tuple/list occurrences of the 15 changed IDs: zero mismatches and zero unresolved values. This check does not claim coverage for other assertion shapes or execute the repository verifier.

## Verification actually performed

- Full Git blob/SHA256/byte checks for merge inputs and generated postimages.
- Exact forward/reverse edit checks for the production adaptations and append-only additional QA edits.
- Complete upstream changed-Rust lane-interface scan: 110 files, 11 original old-lock calls, zero remaining calls in the candidate scope.
- Final tree comparison over 24 changed Git tree nodes: 158 listed changed leaves, no hidden changes.
- Exact fixed source-QA tuple parsing as described above.
- The existing 872b Actions API snapshot still has total_count 0; no admission or execution was inferred.
- The old edaf caller completed successfully at its own source identity. Its original record is archived by the root agent and is not a candidate result.

## Validation still required

Rust formatting, repository source tests, owner/parser gates, full caller proof, Rust compilation, ordinary/Root native suites, platform checks and all required CI checks have **not** executed on this candidate. No prior PASS is transferred. This review grants no scientific, deployment, recovery or actor qualification.
