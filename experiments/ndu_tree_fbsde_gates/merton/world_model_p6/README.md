# P6 — learned joint World Model and real-budget finite cognition (research)

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL / NO MAIN MERGE / NO MODEL PROMOTION.**

Stacked only on P5 PR #2581 at exact immutable source `ded66a28c186a8963c7781df3f091968758791e3`. This is a strictly additive, standard-library-only **synthetic** research slice. P0–P5 evidence, genuine Qwen3 Reader workflow, original source/model/parser and every production Rust owner are unchanged. This is not a neural FBSDE solver, LLM weight training, a production action selector or proof that NDU is superior to same-profile ordinary optimization.

## Mechanism

1. **Training time:** 1,024 disjoint synthetic binary-XOR worlds (512 in each observable regime), with four fully observed probe fields, fit a 32-state *joint categorical conditional World Model* by declared Laplace pseudocount. The model learns `p(Y,bit0,bit1,hint,duplicate|regime)` without using the separate held worlds. These are **4,096 observed synthetic training fields**, not physical tool invocations or measured token savings.
2. **Inference time:** 128 fresh, disjoint synthetic held worlds (64 per regime), each with a hidden binary result. A policy receives only the public regime and its earlier purchased probe outcomes. Each probe costs declared finite *synthetic token units*, drawn from two token units and two call slots. `submit0`, `submit1`, and `abstain` are explicit legal terminal actions. Common-driver `duplicate=bit0` makes marginal independence false; complementary `bit0+bit1` is useful in the easy XOR regime.
3. **Two-scale control:** 6 policies independently execute their selected, online probe sequence against each held world. Controls are direct, one-step VOI, risk-neutral finite Bellman, fixed-risk recursive Bellman, endogenous bounded-risk (NDU-inspired **discrete** special case), and **ordinary same-profile** full Bellman. Last two must have *identical decisions* under identical evidence and recursive aggregator. No online model parameters or objectives mutate.
4. **Recursive utility:** for each admissible action, `rho_alpha=(1-alpha) E[continuation] + alpha min(continuation)` with a bounded preference `alpha(state)` depending on TRAIN-derived posterior uncertainty and actually consumed resources. The external score is always `observed success - (3/50) * synthetic probe tokens`, under a fixed objective independent of the controller's internal alpha. No statement of general NDU/FBSDE well-posedness is made.
5. **Independent postseal audit:** A second pure-Python implementation rebuilds all training-world counts from original algorithmic bytes, recomputes every held outcome from a separately coded SHA256 generator, solves the *entire* finite control problem independently, verifies **all** actions/observations/budgets and full six-policy task census, rejects forged or resealed attempts, then opens the hidden answer and evaluates terminal accuracy and complete synthetic inference resource usage. The source generator seed is public and deterministic: this is **reproducible synthetic evidence**, not authenticated hidden/future labels.

## Already observed local negative result

Python 3.13.5, one process, exact source, 18/18 normal and 18/18 `python -O` tests plus compile checks:

| Policy | Held correct / 128 | Synthetic probe calls | Probe token units | External net utility |
|---|---:|---:|---:|---:|
| Direct | 66 | 0 | 0 | 66 |
| One-step VOI | 81 | 64 | 128 | 1833/25 |
| Risk-neutral Bellman | **109** | 256 | 256 | **2341/25** |
| Fixed-risk | 97 | 128 | 128 | 2233/25 |
| NDU discrete | 97 | 128 | 128 | 2233/25 |
| Ordinary *same-profile* | 97 | 128 | 128 | 2233/25 |

The risk-neutral strategy **outperforms NDU discrete on this synthetic external target**; same-profile ordinary optimization matches NDU exactly. This is an important negative control. Neither exact finite optimization, residuals, nor a favorable comparison to the *direct* arm proves an NDU-specific learning or reasoning advantage. No part of these synthetic values can be substituted for P5's authentic Qwen3 original-model, publisher-label or physical-cost receipts.

## Reproduce and falsify

```sh
D=experiments/ndu_tree_fbsde_gates/merton/world_model_p6
python3 -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 -O -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 -m compileall -q "$D"
python3 "$D/world_model_p6.py" --output /tmp/p6-first-attempt.json
python3 "$D/independent_audit.py" --attempt /tmp/p6-first-attempt.json --output /tmp/p6-first-audit.json
```

Both write paths are create-only; use a new path per run. CI is read-only and additionally enforces source/tests/strict-replay matching; it does not waive `blocking-ci`. Artifacts contain neither original AG News text nor pretrained weights and carry no authority.

## Next scientific gates

* Connect a **versioned, label-blind** instance of this control interface to newly completed P5 original-model receipts without retrospectively changing P4/P5 answer grammar or candidate sets.
* Demonstrate **genuine learned** (neural) World Model predictive calibration and action-conditioned performance on independent source families and future windows, including OOD and parameter-gradient tests.
* Report actual online model calls, full lifecycle CPU/GPU/wall/tokens/latency and the independent source outcome, not synthetic unit consumption or cost saved by replaying a paid slate.
* Admit stochastic NDU FBSDE only after independent well-posedness, covariance-coordinate, conditional-moment and convergence qualification; retain same-profile Bellman equality as a required negative control.
