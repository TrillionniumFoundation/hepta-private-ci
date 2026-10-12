# Frozen Reader order sensitivity: retrospective counterfactual paired audit

Research-only companion to PR #1546. No model calls, retraining, source editing,
production switch, FBSDE/NDU logic or Writer API changes are made by this audit.

## Immutable input and admission

The existing completed [160-call counterfactual Reader experiment](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38234318024) generated source `f3609d11cbe715c0202cb09e1463fa4ad002bd3d`, source tree `4846438b33ccf78ef715011f9c181488848f850b` and artifact `11744278119` (ZIP SHA256 `9ee9e63a725b3a5598ba6e89d728d6b17582d60853ee994151c1b58a15bf4a95`). Original `native/raw-answers.jsonl` SHA256 is `cf3c06d54d86d6a9ea44e08a86083cd583fb319774468e6ad1acae7c57d4ec40`, with 160 registered rows. The complete internal SHA256SUMS, source commit and tree, question and selected-source identities, all Reader identities/receipts and the exact original scoring are validated before any audit output.

The experiment has **16 matched causal pairs, 32 question variants and five Reader conditions**, *not* 160 independent natural-language tasks. Within a pair, the same question words and global evidence-token multiset are maintained while one typed relationship changes the correct answer. The two full-evidence conditions use the same three source identities but reverse their order. This is descriptive evidence-order diagnosis, not a new randomized trial or causal identification in real language.

## Actual completed result — no newly generated model answers

| Arm | Exact target token in Reader output | Hit 64-token cap | Correct full answer with bound citations |
|---|---:|---:|---:|
| BM25 top3 | 6/32 | 19/32 | 0/32 |
| Joined top3 | 3/32 | 11/32 | 0/32 |
| Reversed joined top3 | 16/32 | 16/32 | 0/32 |
| Missing first relation | 8/32 copied target without path | 22/32 | 0/32 |
| Only terminal relation | 0/32 | 31/32 | 0/32 |

Among the **16 matched pairs**, reversing otherwise identical full-evidence source order increases the number of literal-exact target outputs for eight pairs by two, leaves six pairs tied, decreases one pair by two and one pair by one. Both counterfactual answers have the exact single target literal in **1/16** pairs in normal order versus **8/16** pairs in reversed order. The Reader generated exactly the same raw answer despite the required counterfactual flip in **7/16** pairs with original order and **3/16** with reversed order. Neither ordering produced even one pair with **both correct answers and complete evidence citations**.

Critically, this does **not** establish generalized inference or an improved source-grounded solution. The criterion “single correct target token appears in model output” permits an unsupported copy, and the model often copies input evidence as output. More token generation or source reordering cannot substitute for independently verified citations or missing-evidence refusals. Seven and five output variants also remain correlated by scenario and template.

## Qualifying next steps

The separately queued 128-output-token experiment changes **decoder compute**, not the frozen Reader or evidence identity; it must preserve the original first 64 generated token IDs before its additional output may be analyzed. The previously blocked three-prompt contrast needed one Ruff F841 cleanup (unreferenced test variable), not a new training policy. New prompt or decode candidates must report, separately, target literal, exact refusal, citation syntax, *actual* evidence support and token cost. Never choose the most favorable prompt/order on an already-exposed test slice and call that held-out confirmation.

This audit is runnable offline from the pinned artifact and plain Python source:

```bash
PYTHONPATH=scripts/memory_cell python scripts/memory_cell/system2_counterfactual_order_audit.py \
  /path/to/pinned-160-call-archive.zip /path/to/new/order-audit.json
```

The isolated workflow downloads the exact original GitHub artifact, pins its outer SHA256, validates each member and original answer, runs focused pure-Python tests and scoped Ruff, emits the read-only summary and preserves a source-hash manifest. The full inherited MemoryCell regression remains a separate mandatory GitHub job on the same research head. **No post-hoc metric in this file authorizes production promotion.**

`production_accepted=false`; `general_ndu_fbsde_gain=false`; `independent_natural_task_evidence=false`.
