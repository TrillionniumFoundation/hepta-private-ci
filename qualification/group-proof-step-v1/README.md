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


## Independent original-source replay

The campaign now retains the **full synthetic public heldout source text** and its
original constructor label once per test case. The separate
`group_proof_step_review.py` is stdlib-only and intentionally imports neither
the trainable policy nor its proof oracle. It independently parses public facts,
reconstructs all five counterfactuals, hashes each modified prompt, checks
constructor labels against the actual evidence, binds frozen training weights
and exact source-group census, replays each raw prediction/work/latency row,
and recomputes every score. Duplicate rows, altered source truth,
mismatched interventions, invented labels, forged work, score inflation and
authority claims are fatal. Ten new fault/acceptance tests verify the reviewer.

`python3 -S qualification/group-proof-step-v1/group_proof_step_review.py
/approved/group-proof-observations.json --output /sealed/group-proof-review.json`

This is **read-only consistency** of synthetic original evidence, not an
externally signed source publisher, model execution attestation, independent
future chronology, real Granite task, or a new proof of general reasoning.
The independent review must succeed in hosted CI before a diagnostic claim
is considered, and still provides no production promotion authority.
