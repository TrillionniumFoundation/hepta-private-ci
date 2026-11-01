# Independent historical quality and cost accounting

This module reads retained R12 content evidence without importing any R12
implementation, executing a model, loading a checkpoint, or changing a candidate.
It reconstructs accuracy, cross entropy and Brier scores from all original NPZ
prediction arrays. This is historical reanalysis after outcomes were seen, not
new held-out confirmation or a replication of the original training.

From the repository root, use a fresh destination:

    python -B -m experiments.hcsn_validation_r13_20261031.cost.audit freeze \
      --output experiments/hcsn_validation_r13_20261031/cost/results/historical_001
    python -B -m experiments.hcsn_validation_r13_20261031.cost.audit run \
      --output experiments/hcsn_validation_r13_20261031/cost/results/historical_001

Dependencies: Python 3, NumPy and Matplotlib. No Torch or GPU is required.
The freeze command writes the exact source, protocol and minimal input
manifests before analysis. Paths in the input manifest are repository-relative,
so the original bytes can be packaged without checkpoints or training traces.
The run command uses a fresh, one-thread child and retains a complete Linux
wait4 CPU/wall/RSS receipt including imports, input hashing, raw-score
reconstruction and figure output. It will not overwrite any existing result.

## What is checked

- All frozen analysis and input bytes match SHA-256 and byte counts.
- The retained R12 protocol, source freeze and copied content source match.
- Recorded checkpoint SHA links and minimum-validation selected steps match.
  Checkpoint payloads are not read or rehashed.
- Every original process receipt has a matching log hash and valid nonnegative
  resource measurements. Failed attempts, when supplied, remain in the totals.
- Every expected job has training/evaluation/profile receipts as appropriate.
- Profile input identity matches the selected validation input; there are twelve
  repeats per batch size, three warmups and one thread.
- All raw prediction tables reproduce their published scores and input identity.
  Methods share identical retained labels, episode/group IDs and input hashes.
- Shared donor training is counted once in the research total. A separate
  standalone-candidate scenario charges the full donor training cost.

Original commit names inside receipts are preserved claims, not validation of
remote publication. The copied audit_results.py is neither imported nor needed.
The input manifest is the exact required evidence inventory; it is not an
assertion that every original experiment or failed run outside that inventory
has been discovered.

## Interpretation

The Pareto figure uses IID accuracy and actually measured validation-IID-shape
warm CPU. The stress-domain table keeps unmeasured domain inference cost empty.
It never assigns short-sequence latency to a long-sequence result.
Three fitting seeds share fixed synthetic datasets; repeated profiles are
timing repetitions, not independent model fits. Frontiers of seed means are
descriptive and do not constitute confidence bounds or superiority tests.

The eight candidates are real architectures under a fixed 128-update budget,
not a claim that family-specific tuning or optimized accelerator implementations
were exhausted. Frozen mode freezes only the common causal frontend.
The analytic content candidate is an expected-renewal gate with fixed physical
parameters. It is not a complete density-state or He–Xiong free-boundary model,
and it does not inherit numerical-kernel or action-value qualification.

Amortization reports (donor CPU + fit/selection CPU)/N + warm request CPU.
It does not price CPU, combine quality with money, estimate energy, or count
unmeasured production startup as zero. R12 training, evaluation and profiling
totals are shown separately; nested timing is never added a second time.
Current read-only powercap/hwmon/NVIDIA visibility is recorded separately from
historical R12 energy, which was not measured.
