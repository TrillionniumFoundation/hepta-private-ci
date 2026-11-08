# Capacity audit and development episode trainer

This continuation implements configurable official baseline adapters and an
ABC/D-only training path. It does not admit the six-family formal experiment.
All scientific, confirmation and production conclusions remain **HOLD**.

## What is implemented

`models.build_model(..., width=...)` configures actual hidden dimensions, with no
padding parameters. Omitting width preserves the original interface dimensions.
CfC uses its official default-mode cell, PLIF uses the official recurrent spiking
node, and S4D uses the verified official checkout. Missing dependencies fail;
there are no substitute models. Every forward starts a fresh episode.

`capacity.py` chooses widths by registered trainable real scalar counts before
reading any task labels. Complex entries count as two real scalars; frozen
parameters are separate, aliased storage is rejected, and a label-free backward
probe reports disconnected parameters. An unmatched roster fails without padding.
This is not a proof of scalar identifiability or numerical qualification. The
target integer must separately be bound to the intended HCSN source and physics.

`episodes.py` verifies the original archive/member hashes. It excludes E before
interpreting event labels, coordinates or timing. Selection is frozen before
feature fitting: A/B/C train, D development, integer tick then source-row order.
The default uses the protocol's first/middle/last 128-event windows per sequence.
`all-development` uses all A/B/C/D events in nonoverlapping 256-event windows,
retaining each shorter final window. An artificial window's first gap remains
the original gap, rather than being reset or clipped. Frontend statistics and
inverse-square-root class weights use all A/B/C events only.

`train_development.py` requires a numeric wall/RSS envelope and an exact prepared
manifest hash. The caller must additionally enforce the hard process envelope.
It uses AdamW and preserves the official S4 learning-rate/zero-decay parameter
groups. Windows have fresh state, within-window order is unchanged, and the
seeded window permutation is shared across architectures. Every update checks
all trainable tensors for connected, finite gradients and retains started and
completed optimizer events. Checkpoints retain model, optimizer, RNG and cursor.
There is no automatic resubmission or resume route.

The optional memorization diagnostic uses the first multiclass **training**
episode. Its updates and metrics are separate. It restores and checks every
initial state tensor and the Torch RNG before the main optimizer is created.
Passing requires accuracy at least 0.95 and present-class macro-F1 at least 0.9;
failure remains visible. An update cap or epoch cap is not convergence. The
runner never sets `training_adequacy_established` to true and has no E/HCSN
confirmation command.

`audit_training.py` reads the retained main-fit AdamW second moments and the
initial/final tensors. It reports real scalars with positive gradient moments,
actual parameter changes, and changes with zero gradient moment separately.
This prevents weight-decay-only changes from being represented as observed
gradient use. It validates optimizer membership, step counts, immutable hashes,
and started/completed journals. It performs no new training. Zero second moment
does not prove structural disconnection; the count is an observed numerical
coverage measure, not a certification of functional degrees of freedom.

## Reproduction

Use the pinned dependencies in `dependencies.json`. Every output file/directory
must be new. From the repository root, for an implementation validation:

```sh
python proposals/localization-v2/capacity.py --target-real-scalars 9804 --s4-repo /pinned/s4 --output /new-run/capacity.json
python proposals/localization-v2/train_development.py prepare --archive /data/official-localization.zip --output /new-run/data
python proposals/localization-v2/train_development.py fit --prepared /new-run/data --manifest-sha256 MANIFEST_SHA256 --output /new-run/gru --arm gru --width 44 --seed 101 --epochs 1 --max-updates 12 --memorization-updates 16 --learning-rate .003 --weight-decay .0001 --gradient-norm-cap 1 --wall-seconds 140 --rss-bytes 2147483648
python proposals/localization-v2/audit_training.py --fit /new-run/gru --output /new-run/gru-audit.json
```

`MANIFEST_SHA256` is the exact digest printed by preparation. The 9,804 target is
the historical frozen-physics **interface** configuration, whose numerical
admission covers only the old A01/D01 selections. It is not full-context HCSN
admission. For S4D, the fit command also requires `--s4-repo /pinned/s4`.

Development metrics include all-11-class macro-F1, present-class macro-F1 and
balanced accuracy, uncalibrated NLL, 15-bin equal-width ECE, and Brier defined as
one half the summed squared class-probability error. These are D diagnostics;
there is no E evaluation, temperature fitting or comparative efficacy claim.

## Executed implementation validation

The retained source-v1 archive is SHA256
`b8138610c41e5e78d41dfb78e40f35ab1a344ca23ca87422b2a7d9c87ec418d3`,
based on `5f7f55e015dde7fab0c174081fef090ff45501de`. Five regression methods passed,
including all five official adapters. One shared seed, 101, produced five fresh
baseline fits; each completed 16 diagnostic and 12 main optimizer updates.
Every main fit used the same 12-window prefix and observed label IDs 0, 3, 4, 6.
The partial first epoch is explicitly recorded as incomplete. Shared frontend
statistics used 89,216 A/B/C events; the selected preparation contains 45 train
and 15 development episodes.

| Adapter | Width | Trainable real scalars | Positive main-fit gradient moments | Short memorization diagnostic |
| --- | ---: | ---: | ---: | --- |
| GRU | 44 | 9,867 | 9,867 | Did not meet thresholds |
| Official CfC | 19 | 9,492 | 9,492 | Did not meet thresholds |
| Official recurrent PLIF | 82 | 9,770 | 6,236 | Did not meet thresholds |
| Official S4D-Lin | 54 | 9,785 | 9,785 | Did not meet thresholds |
| Causal attention | 26 | 9,423 | 9,423 | Met this training-only diagnostic |

All five NLL values fell on the diagnostic training episode, but four diagnostics
failed the registered accuracy/F1 thresholds. This is implementation evidence,
not training adequacy or an architecture ranking. Measured peak process RSS was
approximately 642–650 MB. Energy and full physical cost remain unknown.

The retained-state audit found all trainable scalars changed, but PLIF had
3,534 changed scalars with zero retained gradient moment. Those changes cannot
be counted as nonzero-gradient use; all five fits used nonzero weight decay.
Its registered parameter count therefore must not be presented as evidence of
equally used capacity. The other four models had positive moments for all their
trainable scalars. All five had identical window-order digests and complete
started/completed update journals. This audit used no new training and took
2.468 seconds; its summary SHA256 is
`eed311caf6e3b97ad37a2c4a5d81b815d52c8b984b0d9c4b83a79845db8ff1db`.

The first native attempt failed before launching the missing historical Python
environment. The next retained attempt reached regression and failed because
the historical S4 working tree lacked source files. Dependencies were rebuilt
inside a new directory from existing PyTorch, a pinned ncps Git archive and the
retained official SpikingJelly wheel; S4 was restored from its local Git objects.
The original directories were not edited. Both failures and recovery costs are
retained. Validation retry caps were reduced rather than silently resetting the
original 1,500-second allowance. The successful test/count/prepare/fit sequence
took 50.139 seconds; the measured earlier failed attempts and recoveries took
15.921 seconds. These measurements exclude source transfer and controller-side
analysis and do not establish a complete equal-cost scientific comparison.

The update auditor and this documentation were added after the training source
was frozen. They do not relabel the historical run as execution of a later full
commit. Formal work still needs full-context HCSN numerical admission, qualified
trainable physics, real ablations, complete resource accounting, sufficient
training/tuning and independent confirmation. `formal_fits_started` remains 0.

## Publication identity

The [qualification manifest](../../qualification/hcsn-localization-trainer-20261108/MANIFEST.json)
binds the retained native archive to the four functional source commits and the
separately tested blob-policy backport. Publication applies repository-pinned
Ruff layout changes; FORMATTING.json records the original and formatted hashes
and exact Python AST equality, including the test sources. The native training
archive and separately executed auditor remain their own execution identities.
No training or completed tests were rerun after final formatting.
