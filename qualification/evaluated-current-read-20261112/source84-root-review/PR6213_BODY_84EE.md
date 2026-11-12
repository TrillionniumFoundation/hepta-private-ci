## Why this change is needed

The original evaluated read path repeated physical owner reads inside one no-effect observation, while the owner channels retain strict request and lifetime bounds. The recorded `edaf1d9` native run still had seven failures and one timeout. Later upstream changes introduced bounded same-call Training and CURRENT transactions, but their exact source guards and one Candidate origin fixture did not yet match the consuming helpers.

This draft integrates those changes with the evaluated ReadSet and fixes the observed source-guard and fixture incompatibilities. It remains **HOLD** until the combined immutable source has its own actual results.

## Current immutable source

- Head: `84ee9c2ed0db8b20b792634d775f9b4f97a34578`
- Tree: `6f1d7265ef1a58a0de1cc8da75ce142111743d85`
- Integrated base: `a4a1b5eb6cb45fc1182564e6b81026a2a2acf609`
- GitHub comparison: ahead by 21 commits, behind by 0; 164 changed paths.
- The branch update used an expected-head lease from `872b1b6`; the resulting commit, parents, tree and branch ref were read back. The PR remains a draft and is currently mergeable.

The prepared integrations are preserved in the graph: `c7ba932` joins the reviewed source with d397; `118e8d1` integrates e403; `26f9a14` adds the test-only diagnostic; the current head aligns the equivalent upstream typed fixture repair.

## Resulting behavior

1. **Original CURRENT and Source checks remain tied to the real call.** The combined Selection and NextUse paths have exactly 6 and 9 semantic CURRENT check slots. Their first and final slots perform the original physical CURRENT reads; the same actual Cell and Task allocations are checked throughout. Purpose is fixed once after the first CURRENT and Source input check. The native NextUse ReadSet retains the actual Source publication pair and the independent Selection and Source tail checks. Public Individual entry points retain their original physical reads.

2. **Upstream original-owner protections are retained.** The bounded Training proof, resident-origin checks, owning lane guards and exact caller inventory are integrated. The caller manifest contains 628 boundaries and 429 protected rows; its complete TOML parses to 1,349 function-order rows across 1,310 unique path/function pairs. The allowlist has one active pin for the actual CALLERS bytes.

3. **The actual source-gate and compiler failures receive concrete repairs.** Mutation checks follow the current consuming helpers and preserve both parents' wrapper and physical-read attacks. The Candidate origin fixture now uses the existing original Fresh/Recovered Training command-peer factory, with the original eight pairing cases and zero-frame, CAS, issuance and dispatch assertions intact.

4. **Evaluation failure diagnosis is test-only.** The first original Panel, Qualification or predecessor error category is retained and printed after the original fixture service returns. It introduces no extra owner read, retry, runtime capability or budget change, and formats no payload, signature, request or response field. This diagnostic is not a claim that the underlying Evaluation failure is fixed.

The earlier reviewed Windows held-file observation, codec-width, Linux configuration and bounded Bazel-shard changes remain in the branch. No manual Bazel run or new research actor dispatch was performed.

## Validation and retained failures

- The staged source was independently checked by exact blob hashes, forward/reverse edits and actual Git tree differences. The 374 integration changes 47 leaves within its 49-entry overlay; e403 changes only four QA leaves; the diagnostic changes only two test-related leaves; the final upstream alignment changes only two fixture leaves.
- The complete static inventory contains 61 source-closure files and 506 named Python test methods. The scoped tuple audit resolved 515 literal tuples against all 628 boundaries without a mismatch. These are static checks, **not execution results**.
- Exact-head automatic CI has now been admitted. [Daemon learning native](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43293663231), [shared Cell framework](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43293663217), [Windows private state](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43293663313) and [blocking CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43293663395) are pending or running. No result from an ancestor is transferred to this head.
- The original 374 source gate is retained: 504 distinct methods, 499 explicit `ok`, five nonpassing methods containing 14 error records and one failure. Its unchanged driver reports 489/15; the method and subtest counts are recorded separately. Native compilation was not reached in that lane.
- The separate original 374 shared-library job failed compilation with E0308 before executing any tests. Missing fresh JUnit is preserved as a consequence of that compile failure.
- The original edaf native result remains 1,738 selected methods: 1,730 pass, seven fail, one timeout. Root and later gates were not reached. The new same-connection budget audit also remains a static open issue until its actual source-bound execution is available.

Full original logs, manifests and root review records are being reconciled into the qualification evidence draft [#6198](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6198).

## Qualification status

All 12 complete research and authority gates remain **OPEN**. `owner_decision = null`; `all_blockers_closed = false`. This draft does not merge, deploy, adopt a default architecture, replace an original failure or promote missing evidence to NoUpdate.
