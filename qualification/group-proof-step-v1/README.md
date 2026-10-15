# E0/E3: causal evidence and learned proof-step Cell pilot (research only)

**DRAFT · SHADOW_ONLY · DENY_ALL · not a model/Stem/System2 winner.**

This additive child of the Group V2 three-seed evidence PR #2271 addresses a concrete failure mode: direct eight-way answer prediction from small frozen Granite embeddings remains near chance after 120 updates. It does **not** relabel or erase the negative Group V2 result.

`group_proof_step.py` contains a *deliberately grammar-specific* public-text Reader for dependency chains, a train-only independently checkable line-level proof trace, a five-parameter SGD evidence selector, and a separate online transition checker. The learned policy does not see a final task label, future observations, the training oracle, or the hidden source constructor during inference. The executor rejects bad state transitions rather than inventing progress. Source-group identity is canonicalized across distractor reordering, distinct from exact input bytes, so the training-evaluation fence is not evaded by line shuffling. Frozen policy weights and training-source identities are content-bound.

`counterfactual_panel` constructs original, question-only, critical-premise-deleted, distractor-deleted and truth-flipped arms. A blind reader must answer full/distractor correctly, abstain without sufficient evidence, and track changed ground truth. A truth flip changes a public final-class fact; no target is leaked to the inference call.

`group_proof_step_pilot.py` runs three independent seeded **synthetic** source-hash-split cohorts, trains only on public training texts, and scores against independently held construction labels. It retains every scored action, wall time, candidate-score count, train-source identities and per-arm failures. The policy is intentionally tiny and hand-engineered for *one restricted textual grammar*. A high pilot score is evidence that stepwise supervised state transitions can work on this toy distribution, **not** proof of learning semantics from Granite, natural language reasoning, multimodal generation, continuous NDU/FBSDE, or cost-adjusted System2 advantage. There are no pretrained model forwards or actual native effects in this pilot; whole-lifecycle and target-host CPU/GPU/RSS/p95/p99 remain unqualified.

Run:

```shell
PYTHONPATH=qualification/group-proof-step-v1 python3 -m unittest discover -s qualification/group-proof-step-v1 -p 'test_*.py' -v
PYTHONPATH=qualification/group-proof-step-v1 python3 -O -m unittest discover -s qualification/group-proof-step-v1 -p 'test_*.py' -v
python3 qualification/group-proof-step-v1/group_proof_step_pilot.py --output /tmp/hepta-proof-v1.json
```

**Decision boundary:** Before using this mechanism in the real learned Group loop: align the step labels to real token-snapshot evidence, train a learned step proposer with no grammar-derived label shortcuts, compare to cheap exact symbolic and static/wide/recursive baselines under identical total compute, repeat real source/time-disjoint MultiRC and multimodal interventions, and show independent full-answer utility gains. Split selection and NDU remain proposal-only. Never merge this research artifact into a production effect or action owner from unit-test success alone.
