# R14 complete backend / controller factorial

This experiment adds a complete-content-backend frozen stratum and a joint-backend stratum to the eight inherited sequence architectures. Every task/seed/mode uses one exactly shared controller for all eight cores. A/B and C/D each share identical content weights. Initial STOP is available before acquiring any payload.

The complete timestamp schedule and finite observation budget are public in advance. This experiment does not model unknown future arrival times. READ acquires exactly one next raw frame; STOP submits the current classifier. The label and future payload enter evaluator targets only. The current policy is followed when constructing sample-path Q-pi returns; these individual futures do not establish conditional expected regret.

## Scope

- The three seed identities are inherited from the old trained backends. They are not eight fresh training repetitions and not independent copies of the same dataset.
- Fully frozen means encoder, recurrent core and readout are unchanged, verified by parameter hashes. Joint means all of these and the shared controller can update.
- The analytic family remains the inherited fixed-coefficient renewal activation. The separate zero-delay distributional solver is not used in this network. Full conditional-distribution content learning is still an open integration requirement.
- Seven ordinary candidates include matched ordinary dual and probit, LIF with surrogate gradient, continuous RNN, CfC, selective Mamba-1 CPU reference and SDPA Transformer. Both the matched ordinary pair and the validation-selected ordinary candidate are reported.
- The dynamic actor currently recomputes already acquired prefixes. Its actual execution CPU is charged. The read-all light arm may execute one complete forward. No claim is made about an optimized incremental cache.

## Selection and identity

The protocol, all local scientific source bytes, inherited manifests, 48 initial checkpoints and third-party CfC identity are fixed before training. Validation selects the complete group of eight backends and their common controller. All twelve groups are frozen before any fresh test observations are generated. Selected validation decisions and every heldout decision must agree between causal prefix execution and the offline prefix evaluator. Failures and nonzero worker receipts prohibit accepted aggregation.

## Cost accounting

Training CPU is observed for a complete task/seed/mode group of eight models and their common critic. Dividing that process total by eight would not establish the cost to train one candidate independently. The old shared donor and initial fits, new joint/frozen-group fitting, actual online execution, and scientific evaluator costs are distinct. Full process receipts already include their nested forward timers. Physical Joules remain unavailable. The R14 cost replay uses older frozen models and is not a cost estimate for these new dynamic actors.

## Execution

Run from the repository root with NumPy, SciPy, PyTorch 2.8.0+cpu and ncps 1.0.1 installed. All commands use one CPU thread. Set an output directory that does not exist for a new attempt.

```bash
python -B -m experiments.hcsn_validation_r14_20261101.content.tests
python -B -m experiments.hcsn_validation_r14_20261101.content.study freeze --output experiments/hcsn_validation_r14_20261101/content/results/formal_01
python -B -m experiments.hcsn_validation_r14_20261101.content.launch train --output experiments/hcsn_validation_r14_20261101/content/results/formal_01
python -B -m experiments.hcsn_validation_r14_20261101.content.study candidates --output experiments/hcsn_validation_r14_20261101/content/results/formal_01
python -B -m experiments.hcsn_validation_r14_20261101.content.launch evaluate --output experiments/hcsn_validation_r14_20261101/content/results/formal_01
python -B -m experiments.hcsn_validation_r14_20261101.content.evaluate summarize --output experiments/hcsn_validation_r14_20261101/content/results/formal_01
```

The original R12 content source and exact inputs must first be restored using the pinned R13 reproduction archives. No new test outcome is used to change learning rates, budgets, selection or baseline choices. A failed attempt remains failed and its source snapshot remains available.
