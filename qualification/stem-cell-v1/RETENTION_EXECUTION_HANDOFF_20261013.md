# Retained specialization after Cell split

Parent: `8d3af546e8b6e374638cdcf957d47db90b638c03` (PR #1726).
Tested Python candidate: `da13e663ab17ca94a8c0896029051f8a2987eb33`.
Branch: `research/shared-stem-retained-specialization-20261013`.
Research candidates only; no main merge, installation, model selection or deployment.

## Executed change

The existing matrix_growth/runtime/export path now supports an explicit
`retention_policy` argument to `freeze_config`, selecting config V5. It requires
the existing parent-group growth policy V2 and live measurement/lifecycle contract.
Omission preserves V1-V4 behavior and the old paired-protocol hash, including the
absence of a retention key. No new experiment arm or wrapper runner is introduced.

Four canonical lists bind old_train_groups, new_train_groups,
old_validation_groups and new_validation_groups. They must be nonempty, pairwise
disjoint and cover exactly the supplied pre-cutoff training source groups. Exact
state/question/options duplicates across roles are rejected before model loading.
The final blind eval split and its separately supplied observer labels are unchanged.
Old/new denotes an OFFLINE curriculum here, not proof of newly acquired future data.

The first training stage uses only old_train. The growth residual and group-count
criterion use only new_train. Initial parity uses only the two fitting folds.
After first-stage weights are fixed, detached reference logits are cached for
old replay and both validation folds. Validation labels do not enter optimization,
growth decisions or sibling auxiliary targets. Changed-validation-label regression
checks preserve the trained weight digest. Public Encoder projection stays label-free.

Post-split specialization actually optimizes

    L_new + replay_weight * L_old
          + distillation_weight * T^2 * KL(p_reference(T) || p_candidate(T)).

L_new/L_old include the already-declared local sibling auxiliary when applicable.
KL sums over classes and averages over examples, with detached reference logits;
the test checks agreement with PyTorch batchmean/log_target and nonzero student
gradients. Old supervised labels are retained because a teacher can also be wrong.
The additional reference-bank forward is NOT free: replay, new examples and that
extra forward have separate denominators and all ATen work enters the live meter.
References are cached outputs, not another teacher parameter copy. Their payload
and the largest retained fitting subset enter the existing feature-byte preflight;
indexes, batches, optimizer states and activations are not misnamed feature payload.

Only after second-stage weights are fixed do both validation folds supply labels.
Every old source group must satisfy the frozen maximum accuracy drop AND maximum
mean negative-log-likelihood increase. Every new group must meet its fixed minimum
accuracy gain against the first-stage reference. This intersection cannot hide one
regressing old subgroup behind improvement in another. These are point-estimate
INTERNAL selection gates, not confidence bounds or independent future-task proof.
There is no adaptive threshold fitting, automatic retry or fallback relabeling.

A rejection retains per-group observations, expected final task IDs and actual
work in FAILED; no successful prediction seal is returned. A pass still exports
retention_established=False. Both the policy and true auxiliary-work denominators
are bound through existing exports and paired-protocol hashes. Different retention
policies cannot be described as matched training. Hashes/group IDs do not prove
source authenticity, semantic nonleakage, observer independence or OS isolation.
Rejected attempts must remain in any outer experiment denominator; evaluating
only accepted candidates would introduce selection bias.

## Configuration and tests

The required policy schema is `hepta.cell-retention-policy.v1`; fields are the
four group lists above plus replay_weight, distillation_weight, temperature,
max_old_accuracy_drop, max_old_nll_increase and min_new_accuracy_gain. Values must
be fixed before execution. There are no implicitly selected study thresholds.
The permissive thresholds in the synthetic tests are for control-flow validation,
NOT a scientifically justified deployment configuration. Use the same declared
protocol for the grouped direct-32 control, including any 64M-capacity comparison.
Use the existing matrix_runtime/matrix_export/paired_execution entry points.

The unchanged predecessor passed 165 tests. Final source passed 185 tests twice,
zero failures/errors/skips: 165 retained + 12 training/partition/KL/subgroup +
8 publication/export/source-binding tests. These execute real PyTorch optimization,
reference caching, subgroup rejection, strict metering and the full sealed pair.
A deliberate actual linear-classifier accuracy regression is rejected. A separate
publication test forces refusal after real training to test the failure boundary.
All seven uploaded Python blobs match the tested bytes; compileall and staged
whitespace checks passed. No operator rule or CI gate was relaxed.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m unittest discover \
  -s qualification/stem-cell-v1 -p 'test_*.py' -v
python -m compileall -q qualification/stem-cell-v1
```

Raw logs, source hashes, the actual missing-Transformers failure and a two-run
synthetic diagnostic are in the source package; hashes are retained in the receipt.
The diagnostic uses eight synthetic pre-cutoff rows and two final public-input
rows, with real tiny 896-parameter banks, not pretrained 421M models. It verifies
mechanics and accounting, not quality improvement or equal-total-work efficiency.
The installed-HF attempt failed at import: zero of its three tests executed and
none is included in the 185 passes. No project-cloud/GPU/native/full-repository/
Rust/hosted-CI success is claimed. The working tree is a bounded source mirror.

## Remaining acceptance

This is one offline population generation plus supervised/reference replay. It
neither merges/compresses parameters nor establishes multi-generation retention.
Independent final old/new task panels, owner provenance, repeated-selection control,
full work/energy/request-memory measurements, actual approved model/data execution,
parameter-compressing consolidation/pruning, NDU/System2 and native selection/
recovery, multimodal generation and 1024/4096-Cell qualification remain open.
Internal selection and initial parity cannot be substituted for those results.

KL interface checked against the official PyTorch reference:
https://docs.pytorch.org/docs/stable/generated/torch.nn.KLDivLoss.html
