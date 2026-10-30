# Time-normalized audiovisual encoder

This is the executed replacement profile for the unexecuted original AV seal.
During review, before any formal fit or heldout model evaluation, the common
duration input was identified as a paired-retrieval shortcut. The original
freeze and all train-only receipts are preserved; `../SUPERSEDED.json` records
the reason for the change.

Every clip now supplies exactly 32 observations with `dt=1` for every token.
All clips and both modalities therefore have identical explicit clock inputs.
These are normalized internal time units, not a claim to preserve real elapsed
seconds. This removes direct clip-duration metadata from the network. Audio
and visual features, training-only normalization, actor splits, labels, models,
seeds, optimizer, 128-update budgets and validation selection are unchanged.
Existing nuisance cues and limitations of a small acted-emotion corpus remain.

The new trainer reuses the sealed `PairEncoder`, objective, checkpoint and metric
implementations. Scheduling and selection are copied from the original runner;
only the split loader replaces `dt` with ones, and source/data paths are bound
to this new seal. Parameter counts and probability gates remain identical.
No original-profile formal training result is being replaced or suppressed.

`ADDENDUM.json` preregisters the nonlearned duration-only retrieval baseline,
the fixed-clock main predictions, a zero-content/original-clock counterfactual,
and an exact constant-input null. The original-clock counterfactual is outside
the trained timing distribution and is not an estimate of training the original
profile. Diagnostics cannot select a model or checkpoint and run only after all
21 main attempts have been recorded. Costs are measured separately and retained.

## Execution

Use CPU PyTorch 2.8 and keep numerical-library threads at one. The protocol has
seven architectures, three seeds and the same 128-update fit budget. Validation
chooses a checkpoint at 32, 64 or 128; both its step and complete fit cost must
be reported. The selected weights can have different training exposure.

```bash
python -m experiments.hcsn_real_av_v1.time_normalized_v2.registration verify
python -m experiments.hcsn_real_av_v1.time_normalized_v2.study --model distribution_free_dual --seed 9301 --output /tmp/av-new-fit
```

The complete matrix is launched by a separately archived Linux `wait4` envelope,
which records interpreter startup, model construction, training, validation,
checkpoint selection, retrieval, output writes, and failures. Concurrency changes
affect resource scheduling only and are logged. Raw worker CPU, wall time and
peak RSS are reported; energy and simultaneous aggregate memory are unmeasured.

The original CREMA-D ODbL/DbCL database attribution and licenses in the parent
directory apply unchanged. These data support an offline, small audiovisual
encoder benchmark; they do not establish broad multimodal or language capability.
