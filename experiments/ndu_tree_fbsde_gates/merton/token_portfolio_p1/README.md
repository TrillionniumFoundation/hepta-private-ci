# P1: NDU–Merton reasoning-token portfolio (research / DENY_ALL)

This additive child of [NDU–Merton PR #2319](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2319) introduces a **label-blind, bounded finite portfolio controller** over independent task requests. It is neither a learned continuous FBSDE nor a full neural training replacement. There is **no pretrained Reader invocation** in this patch. All bundled tests use constructed fixtures; no real-model accuracy, compute savings, or NDU advantage is claimed.

## What runs

`portfolio.py` implements a strict TRAIN-only paired-action estimator, finite per-task resource allocation, and seven frozen baselines under the **same immutable external objective and budget**:

- `direct`: no *incremental* reasoning, verification or retrieval expenditure;
- `fixed_reason`: fixed reasoning for task IDs in canonical order, until hard budget exhaustion;
- `greedy`: optimistic per-token TRAIN-derived local return with exact resource checks;
- `neutral`: exact multiple-choice 2-resource knapsack with mean TRAIN outcomes;
- `fixed_risk`: exact knapsack with a fixed 1/4 empirical downside weight;
- `ndu_discrete`: exact knapsack with bounded TRAIN-observed endogenous preference weight;
- `ordinary_same_profile`: ordinary exact knapsack with **identical** NDU-discrete objective and information, required to make the same choices.

For action `a` and observable difficulty bucket `b`, the TRAIN estimate is Laplace-smoothed task success `p(a,b)=(successes+1)/(n+2)`. The downside proxy is the **minimum observed TRAIN source-group smoothed mean**, not a calibrated confidence bound. Define `rho_alpha=(1-alpha)*p+alpha*worst_observed_group`. Each *additional* action receives incremental score `rho_alpha(a,b)-rho_alpha(direct,b)-tariff*reserved_token_ceiling(a)`. The exact optimizer maximizes the sum of these registered marginal scores with **two finite budgets**: reserved additional model tokens and reserved additional latency. This additive pilot **does not implement Merton covariance/hedging**, share computation across tasks, or capture interactions between an action pair.

`ndu_discrete` uses `alpha=clip(1/4 + (1-2*TRAIN_direct_accuracy)/8, 0, 1/2)`; no HOLDOUT answer or future observation enters that update. Because the ordinary matched-profile comparator uses the same objective and information, exact equality is compulsory. A neural-FBSDE or unique NDU win must not be inferred from a preference-profile difference.

## Inputs and restrictions

1. The `manifest` enumerates named actions, **upper bound** incremental tokens and milliseconds per action, total budgets and an explicit utility-unit-per-token tariff. `direct` has zero **incremental** cost, not zero baseline model cost.
2. `TRAIN` holds complete **paired** independent 0/1 outcome evaluations for every registered action on every historic task. At least four tasks and two source groups per trial bucket/action are required. Incomplete pairs and unknown support fail closed.
3. `PUBLIC` holds only task IDs, observable difficulty buckets and source group IDs. Extra keys including future predictions and labels reject. TRAIN and PUBLIC task IDs and source groups must be disjoint. Source IDs are caller declarations, **not authenticated** source independence.
4. The producer receives only `manifest`, `TRAIN` and `PUBLIC`, computes allocations, and writes a create-only attempt with canonical JSON SHA256. It accepts no truth path.
5. A logically separated reviewer later receives the attempt plus **POSTSEAL** original task outcomes and actual incremental token/latency reports for the *entire* action slate. It validates the complete slate and recalculates outcomes, costs and the attempt. This is shared-code mathematical replay, **not independent signing**, cryptographic timestamping, or externally attested CPU/latency.

The postseal reviewer reports both (a) what the selected actions **would have** consumed and (b) the total **already paid to precompute every action**. The difference is *not* realized model-compute savings. The selected policy was **not executed online** in this P1 patch. Real online trial acceptance must invoke the frozen Reader only after each committed allocation, meter prompt/cache/reasoning/output tokens and p95/p99, and compare actual task success and lifecycle cost against identical-condition controls. Such a trial still requires authenticated original Reader artifacts, prospective source families/windows and independently controlled labels.

No inferred task probabilities, finite synthetic examples, observed original model scores or small Head SGD steps substitute for physical new Reader calls, model capacity gains or production promotion.

## Local reproduction

From the repository root, Python >=3.11, standard library only:

```sh
D=experiments/ndu_tree_fbsde_gates/merton/token_portfolio_p1
python3 -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 -O -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python3 "$D/replay.py" producer --manifest /fixed/manifest.json --train /fixed/train.json --public /fixed/public.json --output /tmp/attempt.json
python3 "$D/replay.py" review --manifest /fixed/manifest.json --train /fixed/train.json --public /fixed/public.json --sealed /tmp/attempt.json --truth /postseal/original_outcomes.json --output /tmp/review.json
```

Use fresh `--output` paths each time; pre-existing output files reject. The `test_portfolio.py` cases are deliberately synthetic and include a separately enumerated small knapsack oracle, label leakage, train/held group overlap, incomplete pairs, forged (even resealed) policy outputs, missing/excess-cost truth, duplicate JSON keys, `python -O` and create-only file refusal. Passing tests establishes finite algorithm mechanics **only**.

## Acceptance / next evidence gate

- TRAIN-only calibration and PUBLIC label isolation with frozen model/tokenizer/prompt versions, predeclared action branches and sufficient real held-out Reader evidence.
- Real source and model bytes pinned; accurate **actual** per-arm input/output/reasoning/cache token accounting, CPU/wall and p95/p99 on a named target host; calibration, verifier, trace acquisition and training accounted separately once.
- Seven policies on identical tasks, budgets, outcomes and authorized Reader. Paired independent scorer opens truth only after the real attempt is sealed. Report source-group and future-window uncertainty, net external utility and task accuracy separately, not only internal `rho`.
- Refuse NDU selection when `fixed_reason`, `greedy`, `neutral` or `ordinary_same_profile` matches/outperforms it on external task value per full lifecycle resource cost. Baseline superiority remains a valid negative result.
- No runtime/Neuron/Worker/CNS/FinalUse, model artifact selection, protected CI or `main` mutation. **RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL / NO MODEL PROMOTION.**
