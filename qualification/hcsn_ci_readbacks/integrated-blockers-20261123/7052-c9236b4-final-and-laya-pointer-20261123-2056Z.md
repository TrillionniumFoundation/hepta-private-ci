# #7052 c923 scoped blocking CI final and pinned Laya object identity — 2026-11-23 20:56 UTC

Source: `c9236b4ee6d73a8de3bf4ccb7887a41715738d3c`; prospective merge: `b5ae49b3cfec89c7cc8082587264476c736fb26a`. PR open, draft, not merged. Original [blocking-ci 45240607977](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45240607977) completed/failure; connector returns 24 jobs (below its 30-job first-page limit), all completed. Independently counted 12 success, 8 skipped, 4 failure. This is a **scoped** run, not the prior 46-job full repository suite. No skipped job is a pass.

| Job | ID | Conclusion |
|---|---:|---|
| Codespell / Check for spelling errors | 137923881158 | success |
| Select blocking CI scope | 137923881258 | success |
| Blob size policy / Blob size policy | 137923881280 | success |
| Current TaskFlow v1 migration source-head replay | 137923881321 | success |
| Current TaskFlow v1 migration prospective-merge replay | 137923881602 | success |
| Historical TaskFlow v1 migration ${{ matrix.lane }} replay | 137923883660 | skipped |
| LedgerWriter Bazel ${{ matrix.lane }} replay | 137923884314 | skipped |
| Hepta scoped native checks / shard 1 | 137926049912 | success |
| Hepta scoped native checks / shard 3 | 137926049918 | success |
| Hepta scoped native checks / shard 0 | 137926049983 | success |
| Hepta scoped native checks / shard 2 | 137926050031 | success |
| Hepta contract gate / Validate canonical branch and contract metadata | 137926050055 | success |
| learning.operator qualification / learning.operator deterministic merge | 137926050436 | failure |
| learning.operator qualification / learning.operator exact source | 137926050442 | failure |
| NDU v6 neural rollout smoke / Unified profile and executed-policy regressions / Objective, continuation, and selected-policy invariants | 137926051726 | success |
| Bazel | 137926052194 | skipped |
| NDU v6 neural rollout smoke / Python, native NDU, and real rollout | 137926052518 | success |
| cargo-deny | 137926052777 | skipped |
| rust-ci | 137926054010 | skipped |
| Lightweight prose and derived checks | 137926054199 | skipped |
| sdk | 137926054593 | skipped |
| repo-checks | 137926054825 | skipped |
| learning.operator qualification / learning.operator qualification required | 137942544218 | failure |
| CI required | 137971639015 | failure |

Both strict qualification lanes remain red for the two control-plane diagnostics already recorded. Required qualification and CI aggregation reject failing dependencies. All four scoped Hepta native shards are green; no full native product qualification follows from this. No successful jobs were rerun.

## Exact-source workflow roster

| Workflow | Run | Status | Conclusion |
|---|---:|---|---|
| v8-canary | 45240608153 | completed | success |
| Learning artifacts qualification | 45240608033 | completed | success |
| MemoryCell owner and benchmark continuation | 45240608027 | completed | cancelled |
| Hepta architecture convergence | 45240607968 | completed | success |
| blocking-ci | 45240607977 | completed | failure |

## Laya upstream object identity, not byte acquisition

For the frozen revision `7b928d828b7b0e022f929d9bd2e44165aa270148`, the [upstream raw Git LFS pointer](https://huggingface.co/convaiinnovations/laya/raw/7b928d828b7b0e022f929d9bd2e44165aa270148/model.safetensors) reports:

```
version https://git-lfs.github.com/spec/v1
oid sha256:891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c
size 842609210
```

The [same-revision file page](https://huggingface.co/convaiinnovations/laya/blob/7b928d828b7b0e022f929d9bd2e44165aa270148/model.safetensors) displays the same SHA-256 and Xet hash `dd8562d713759821a0bc049e79abd09e5817d218d18fa51478ad16986d018764`. These web representations may be cached; they establish expected object identity, not fresh delivery. The actual HEAD attempt from the current execution environment failed DNS resolution (curl 6); no bytes were downloaded or independently hashed. Original job 137934297752 explicitly set HF_HUB_DISABLE_XET=1 and installed hf-xet 1.8.0 / huggingface-hub 0.35.3. Do not change transport policy without reviewing its original purpose. Next eligible acquisition must verify exact byte length and SHA-256 before use; retain exact revision and original other files, training and held-out evaluation. No cache/mirror attested, no new training, no repeat dispatch. Laya remains HOLD.

No product source, V1 interface, frozen scientific inputs, or permission/timeout policy changed. #7016, #7021, #7032 and #7052 remain unmerged drafts per readback. Global HOLD.
