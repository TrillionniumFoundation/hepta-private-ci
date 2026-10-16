# V15: cost-bound System2 / conditional Cell Split shadow control

**DRAFT · RESEARCH ONLY · SHADOW_ONLY · DENY_ALL · NO MAIN MERGE · NO FINALUSE.**

## Why this slice is needed

Stem V9 original MiniLM learned Heads lost to complete-source BM25 on historical evidence selection. Stem V13's original Reader did not show additional source-witness hits in its conditioned small comparison. Stacked V14 (#2400) establishes the **contract**, not yet a successful original four-evidence condition Reader execution. No Stem/Cell/SYSTEM2 promotion may bypass Reader sufficiency.

Earlier MultiRC/System2 work (#2283) found that an original native NDU arm changed **zero** predictions compared with the one-step arm and used 102.795 online CPU seconds versus 29.430 seconds in its historical pooled report. This makes an explicit **net value of extra computation** gate essential. Merely implementing an NDU evaluator cannot be counted as a task-performance improvement.

This patch adds the auditable finite-horizon cost controller and no-free-Cell-Split measurement contract. It is a new additive research-only layer atop the V14 source branch; it changes **no production Rust, NDU, Worker, CNS, CAS, FinalUse, or selected model**.

## Exact mathematical/algorithmic claim

For a bounded precommitted decision tree and a special **additive** cost/utility profile, use the following Bellman recurrence. All predictions and coefficients are frozen **before** original Reader output and outcome adjudication.

```text
V(n, b) = max(
    reward_correct * P_predeclared(success | node n),
    max admissible a [
        sum_child P_predeclared(child | n,a) * V(child, b - work(a))
        - cpu_price * cpu_ms(a) - token_price * tokens(a)
    ]
)
```

Computations use Python Fraction for exact rational arithmetic, bounded nodes/branching/depth, explicit hard CPU/token admission and **STOP on equal value**. The source-only planner does not consume labels or answers. This is a **finite-tree additive expected-utility special case**, NOT a general stochastic/fully coupled NDU FBSDE solution, not a well-posedness proof, and not a trained calibrated value estimator. It cannot independently authenticate either forecast probabilities or issuer identities.

Same Reader/input-family/source identity and budgets, four registered arms:

| Arm | Behavior |
| --- | --- |
| `stop` | Stop at the root |
| `fixed_one` | Execute the first registered affordable action, then stop |
| `greedy_one` | One action maximizing expected successor stop-correctness without compute-price optimization, then stop |
| `ndu_shadow` | Solve the finite tree over available CPU, tokens and depth; seal the contingent policy before outcomes |

At every graph node, a **unique SHA-256 of the actual state-conditioned model request** is required. The root must match the case input digest. Observed final-answer rows must bind the exact terminal request digest. No two distinct states may silently share a request hash. A physical cost is reported for every externally executed arm; actual end-to-end CPU and token ceilings are checked separately from *forecast* incremental action costs. The experiment cannot infer a real cache hit or a real GPU forward from a hash.

### Phases

1. **Before any outcome:** freeze source-family/time-window roster, objective, Reader/Stem/tokenizer/runtime SHA, principal, purpose, generation, authority epoch, graph inputs, probabilities and prices. `plan_control` computes all four policies without gold labels. Extra fields are rejected, including future labels.
2. **Original model execution required externally:** execute all registered arms under the same Reader and actual source first. Keep raw answers, source texts, source-label material, real worker/host receipts and physical total costs outside the public Git tree. The V15 script never calls a model and never asserts these external records are genuine.
3. **After the entire answer roster is sealed:** the independent outcome owner evaluates answer correctness and citation entailment. `review_control` re-computes the precommitted policy, verifies every ordered action/observed successor and complete answer/label linkage, reports per-arm actual cost and paired differences. All promotion/quality-qualification fields remain hardcoded **false**.
4. **Cell Split separately:** paired `parent` versus `split` original predictions must use the same immutable cases, with source-independent old/future families, both heads, actual per-arm costs and separate training/migration/evaluation charges. `review_split` rejects disguised old-task forgetting, missing original outputs and forged adjudication bindings. It may report `numeric_gain_gate=true` but never authorizes split.

### Frozen source / external outputs / independent reviewer CLI

Execute at repository root, with original private data supplied from separately authenticated producers:

```bash
python3 qualification/stem-cell-v1/v15_system2_split_shadow.py plan \
  --study PRIVATE/source-first-cost-study.json > PRIVATE/sealed-four-arm-policy.json

python3 qualification/stem-cell-v1/v15_system2_split_shadow.py review \
  --study PRIVATE/source-first-cost-study.json \
  --policy PRIVATE/sealed-four-arm-policy.json \
  --execution PRIVATE/original-execution-prelabel-seal.json \
  --adjudication PRIVATE/postseal-independent-judgments.json

python3 qualification/stem-cell-v1/v15_system2_split_shadow.py split \
  --study PRIVATE/split-source-first-study.json \
  --predictions PRIVATE/paired-original-predictions-sealed.json \
  --adjudication PRIVATE/independent-split-judgments.json
```

The exact closed data schemas are defined by the source and demonstrated through the synthetic fixtures. Source SHA values and claimed principal/family/observer strings **do not establish** trusted identities or independent source groups. This tool neither provisions sources nor creates fake original-Reader receipts.

### Anti-leakage and production gates

- Unknown JSON fields, ambiguous/duplicate keys, nonfinite values, bool-for-integer counters, bad source identity, stem/head/tokenizer mismatch, unreadable or changed plans, duplicate/missing answers and corrupted judgment links must fail closed.
- Probability mass must sum to exactly 10,000 basis points; zero-cost recursive action, graph cycle, multi-parent/merged/unreachable state and over-depth plan must fail closed. The actual trace must obey the *recomputed* sealed policy and correspond to a legitimate successor.
- The split numeric-source threshold is **200 claimed source-family roots**, including at least **50 old** and **100 future** groups, at least **two future windows** with >=30 source families each. Future gain, aggregate old-retention, casewise old-regression ceiling and positive fully charged net utility are mandatory. Merely creating 200 fabricated IDs must never grant evidence attestation or deployment.
- Independently authenticated pretrained Reader and evaluator, complete and matched lifecycle costs, future task outcomes, 3 predecessor/future-window longitudinal evidence, negative transfer, target-host 64/256/1024/4096 Cell memory/recovery and exact-head native/global CI are still unmet.
- All `original_execution_authenticated`, `independent_outcome_authenticated`, `net_task_gain_qualified`, `system2_activation_authorized`, `cell_split_authorized`, `model_promotion_authorized` and `production_authorized` result fields are hardcoded **false**. All decisions are `HOLD_NO_GO`.

## Reproduce the local source-only mechanism

```bash
export PYTHONPATH=qualification/stem-cell-v1
python3 -m py_compile qualification/stem-cell-v1/v15_system2_split_shadow.py \
  qualification/stem-cell-v1/test_v15_system2_split_shadow.py
python3 -m unittest discover -s qualification/stem-cell-v1 \
  -p 'test_v15_system2_split_shadow.py' -v
python3 -O -m unittest discover -s qualification/stem-cell-v1 \
  -p 'test_v15_system2_split_shadow.py' -v
```

Isolated analysis CPU source-only tests: **69/69 normal and 69/69 optimized** with synthetic source/answer/label fixtures, zero genuine Reader/model calls and zero real NDU/FBSDE execution. They include a deliberately fabricated 200-family two-window sample proving the descriptive numeric gate cannot grant FinalUse. Hosted CI and all original model/semantic, resource and production evidence must be assessed independently at the **actual exact commit**.

## Immediate physical next step

Complete V14 Reader sufficiency on original models and independently curated sufficient evidence. If the Reader cannot answer with sufficient evidence, repair it before training another Head or adding NDU depth. Otherwise collect genuine four-arm source-independent, matched full lifecycle experiments to find out if the prospective expected task benefit *exceeds* the real extra CPU/GPU/latency and memory cost. Keep Cell splitting a separately qualified next-generation candidate.

**No general reasoning emergence, multimodal generation, production promotion, 10T/100T capability equivalence, independent human success or production Cell Split is claimed by V15.**
