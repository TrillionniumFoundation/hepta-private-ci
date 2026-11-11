# Core×NDU factorial A/B cross-row task-disjointness preflight — 2026-11-11

**HOLD_NO_GO / DENY_ALL · research-only self-declared guard.** No training, owner attestation, live downstream action, independent evaluator, Adopt, cold recovery or deployment is established by this patch.

## Exact source boundary and independent scope

- Repo: TrillionniumFoundation/hepta-private-ci. Parent [#5973](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5973), exact HEAD 789e6d0d87234e584738db346d74548c7e83fc48.
- Unmodified parent qualification/neuroscience-20261110/factorial.py Git blob c9b4b914bdbbe66c5b410b114c5b09724035222b; inherited source blobs were independently checked using git hash-object.
- Execution host: HeptaRuntime ai395; isolated /home/qq/work/neuro4-train-eval-disjoint-20261111-turn6/qualification/neuroscience-20261110/ (exact parent sources copied). No concurrent workspace edited.
- Existing #5973 seed-identity and #5970 evaluator/cell contracts preserved. Changes do not overlap native Agentd/Q24 owner PRs #5971/#5978.

## Reproducible counterexample (before patch)

Each row required source_task_digest != workload_digest. Across two different seed clusters, or two episodes of one seed, a task could be future B evaluation in one block and training A in another. All four arms retained matched budgets, evaluator and seed identities. Nominal prospective statistics were returned without rejection.

The 3 new synthetic tests: two negative tests reproduced the defect (both expected ContractError were NOT raised), and one legal shared-training-A control passed. Original PARTITION_RED.log: 3 tests, 2 failures; 0.12s wall, 0.10s user CPU, 0.01s system CPU, 22,164 KiB peak RSS. This is the unchanged pre-fix output.

## Minimal fix and verification

Build run-global sets of all declared A training-task digests and future-B workload digests; reject their intersection before computing any contrasts. Repeated A tasks in different valid trials are permitted, and the four paired arm references remain permitted. Add coverage.declared_train_eval_task_disjointness = SELF_DECLARED_ONLY, explicitly not evidence of owner custody or semantic task independence.

- GREEN: python3 -m py_compile factorial.py test_partition_overlap.py; python3 -m unittest discover -v -s . -p 'test_*.py'; 43/43 tests pass. PARTITION_GREEN.log: 0.44s wall, 0.42s user CPU, 0.01s system CPU, 23,048 KiB peak RSS.
- Changed factorial.py: Git blob c91b646683120d9d887813adeb610230f16c9ae2; SHA-256 8d4988591442481c6c5e6226436e6523e8a07599830715d6b342a04d2b7d5da6.
- New test_partition_overlap.py: Git blob d3d2a8249b00c01401ddd0609f13d6584143c03e; SHA-256 f99f7954f5e8eafb1e9bce02eea49c267ec6d83e9a63865c5ec45938a802cbc1.
- Inputs are deterministic synthetic labels, declared seed labels 0 and 1, four factorial arms, sparse density, ep0/ep1; model checkpoint NONE; actual task results NONE; independent evaluator receipt NONE; training GPU/Colab/Kaggle unmeasured. Reported resources cover only Python tests, not a model lifecycle.

## Remaining decisive HOLD gates

Owner-authenticated source/action/effect chronology, genuine Q24 candidate, frozen A→future independent B→signed NoUpdate/Adopt→different C→cold recovery; ACT/CTRL sparse/dense delayed outcomes; MEM exact RAG, replay/revocation/retention; seven-lineage full-cost matched controls; and prospective Core×NDU 2×2 independent repeat training are all unclosed. Hash labels do not prevent an adversary from assigning different strings to semantically identical tasks. This cannot qualify scientific efficacy, promotion or production deployment.
