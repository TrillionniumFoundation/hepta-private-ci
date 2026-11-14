# Pinned Fashion H/A/N controls: software only

This package adds a reusable objective and fairness interface to `ndu_training`.
It does not modify the old finite12 scorer, restart CV, read Fashion data,
construct a dataset runner, or establish a real training/quality improvement.

## Objective, model and source identity

For every offline row, with fixed K=4, sigma_aux=.05, tau=.04 and rho=2:

- H = CE(p,y) + MSE(mu,x)/.04.
- q_k = exp(-MSE(clip(mu+.05*epsilon_k,0,1),x)/.04).
- A = H - .1*p_y*mean(q_k).
- Z = 1-p_y+p_y*mean(exp(-2*q_k)); N = H - .1*(-log(Z)/2).

Here A/N name the complete losses; `metrics.auxiliary` is their respective
reward, not that complete loss. The image MSE averages 784 pixels, the
auxiliary average uses exactly four draws, and the CE uses natural logarithms.
`joint_risk` uses `expm1` and `log1p`; CE and logits VJPs retain the non-target
softmax complement when the reported target probability rounds to one.
Clipping uses zero derivative at exact endpoints, not a claim of smoothness.
Finite-K N is exact for that discrete auxiliary law; it is not an unbiased
population entropic estimate/gradient. No q, Z or gradient is floored.

[BINDING.json](BINDING.json) binds `model.py` and `autodiff.py` from commit
`99001f4ac6598914b26f66de977e190341c51dbc`, including original and derived SHA256.
The only source transformation is one model import changed to relative import.
The copies are local dependencies, not imports from another worker's moving
checkout. Source hash verification runs before constructing every control.
The independent terminal derivation/reference hashes are credited in the same
binding, but those files are not runtime dependencies and their old 140 checks
were not rerun. Source dependencies remain separately reviewable mechanical
copies; new behavior is in `objectives.py`, `fairness.py` and `test_controls.py`.

## Paired update and serving contract

Create a `Batch(noisy, clean, labels, draws, weights, normalizer=None)` once and
pass that same immutable, owned data to `Control("H"/"A"/"N", seed)`.
Canonical storage is immutable bytes with fixed dtype/shape tuples, not a shared
ndarray header. Every public array read returns independent metadata, including
its base view, so changing a returned view's dtype/shape cannot alter later
reads or another arm's inputs. The digest binds canonical dtype, shape and bytes.
`loss_grad(batch, sequence)` and `step(batch, sequence, learning_rate=...)`
backpropagate through the original encoder, both heads and every feedback use.
The default sequence is not chosen for the caller: it must be explicit.
H receives the same batch/draw identity but skips unnecessary auxiliary work.

All terms receive exactly the same row weight. Reduction is
`sum(weights*complete_row_loss)/normalizer`; default normalizer is row count,
appropriate for unnormalized importance weights. A normalized weighted mean
requires explicitly supplying sum(weights). Neither clipping nor rescaling
weights happens silently. This choice must be frozen across all arms.

`serve(noisy, sequence)` accepts no label, clean image, draw or sample weight.
It returns the original argmax classes and float32 mean-image outputs.
`offline_service_utility` scores those actual returned pixels separately:
correct-greedy-class * exp(-MSE(returned_mean,x)/.04). A positive auxiliary
reward with wrong greedy class can therefore have zero service reward, and
perfect mean output can still have lower perturbed-image reward. This module
is not a wire serializer/transport audit and does not certify decoded bytes.

## Fair budgets and false-positive control

`require_matched` requires H/A/N plans with identical model binding, seed,
data/split, encoder, optimizer, sampling, applicable optimization and static
decoder opportunities, complete CPU/work caps and executor identity. In
particular, A gets all applicable optimization, not an intentionally slow path.
`BudgetBook` charges full shared cost to every actual consumer and dedicated
cost only to its consumers, retains actual overruns as failures and reserves
finalization tails. It is an interface, not instrumentation: the eventual
runner must observe process-plus-descendant CPU from process birth through
imports, preparation, training, selection, checks, export/receipt and service.
An H/A arm may use its cheaper objective for more real updates within the same
cap. No padding or equal-update-count requirement is imposed. Dot CPU must not
be combined with historical Codex-cloud CPU as one measured system budget.

`holm_gate` is only a transparent multiplicity helper. It demands every claim
in the supplied predeclared family and rejects missing/nonfinite values. It
cannot establish independence, validate supplied p-values or prevent a caller
from changing the family. Freeze/hash the complete claim family before any
new observation. Synthetic helper checks are not a statistical discovery.

## Verification and future work

Run only the new hand tests from `qualification/joint-generation`:

    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
      python3 -W error -m unittest ndu_training.fashion_controls.test_controls -v

See [HAND_REPORT.md](HAND_REPORT.md) for bounded execution and retained logs.
See [PROSPECTIVE.md](PROSPECTIVE.md) for the non-executed next-study checklist.
