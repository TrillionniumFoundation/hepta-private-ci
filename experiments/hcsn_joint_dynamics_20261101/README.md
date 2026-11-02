# Retrained state–content association diagnostic

This additive experiment continues `a793d55c23a7742378b081b162252da428a9fdb2`
(PR #4548). It keeps the original dynamics task and information interface. It
replaces the earlier execution-only association ablation with independently
trained full Flow, factorized Flow and strong Transformer arms on identical
training streams. The intervention is the original `factorized_content` at
observed read boundaries. It retains the complete state probability vector and
therefore does not test whether that probability vector is necessary.

Read REPORT_ZH.md for the measured negative result and COST_LEDGER.json for costs.

The adopted protocol is `results/run002/PROTOCOL.json`: three new training seeds,
600 updates, batch 24, final checkpoint only. Source hashes precede training;
all nine checkpoints are sealed before new confirmation seed 124731 is opened.
The predeclared primary outcome is the first query after the missing forcing
jump. The advancement rule requires positive differences in all three training
seeds and a positive conditional paired-episode interval against both arms.
Intervals condition on the three trained checkpoints and do not describe
uncertainty over training seeds or unknown generators.

The superseded `run001` used the original study's training seeds. This was
caught before confirmation; its original source, completed fits, source-identity
guard failure and complete outer CPU meter are retained as development cost.
Its results do not enter confirmation or support an independent-retraining claim.

From the repository root, with CPU PyTorch, NumPy and one thread per worker:

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m experiments.hcsn_joint_dynamics_20261101.campaign --phase freeze --out /tmp/joint-new
python -m experiments.hcsn_joint_dynamics_20261101.campaign --phase train --out /tmp/joint-new
# Freeze ALL_CHECKPOINTS.json and its protocol/source hashes before confirmation.
python -m experiments.hcsn_joint_dynamics_20261101.campaign --phase confirm --out /tmp/joint-new
python -m experiments.hcsn_joint_dynamics_20261101.audit
```

`audit.py` defaults to the adopted saved run002 and reconstructs all original
inputs and paired contrasts without importing the campaign or model.
`hcsn_four_stage_flow_20261031.meter` wraps train and confirmation processes;
its outer CPU measurements contain inner fit CPU, which must not be added twice.
Runtime versions are recorded. New results from PyTorch 2.6.0 CPU are not claimed
to reproduce the previous PyTorch 2.9.0 checkpoints bit for bit. Equal updates
and information do not imply equal compute. GPU, device joules and full model
adoption are outside this finite-task diagnostic.

The separately frozen SECONDARY_PROTOCOL.json and factorial.py add the full
training-by-execution association diagnostic. Run factorial confirm only after
the primary outputs exist; audit_factorial reconstructs its raw four-cell scores.
