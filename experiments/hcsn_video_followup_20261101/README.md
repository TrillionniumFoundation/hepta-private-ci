# Video increment follow-up

This additive study continues exact four-stage baseline `a793d55c23a7742378b081b162252da428a9fdb2` (PR #4548). It evaluates a fixed temporal-DCT mouth-motion representation and repairs the prior pooled out-of-fold calibration design by using direct logistic probabilities with nested actor exclusions. All model and feature choices use original training actors only. The six original validation actors are historical development data, not a new independent population.

`PROTOCOL.json` defines candidates and gates. `restore_inputs.py` selectively restores only hash-bound train/validation arrays and fixed-prefix numerical feature caches from the original evidence parts. If the inherited parts are sparse-excluded locally, it reads their bytes through `git show` at the exact baseline commit. No test, eight-actor reevaluation, or actor 1019 inputs are required.

Run from the repository root with NumPy and SciPy, using one BLAS thread:

```sh
python3 -m experiments.hcsn_video_followup_20261101.restore_inputs
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python3 -m experiments.hcsn_video_followup_20261101.study prepare \
  --out /tmp/hcsn-video-new-run
# Preserve and publish source/protocol/input identity/candidate freeze first.
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python3 -m experiments.hcsn_video_followup_20261101.study evaluate \
  --out /tmp/hcsn-video-new-run
```

The guarded run002 supersedes run001 for evaluation; all six numerical checkpoint/output files are byte-identical between those training runs. Run001 is preserved because independent review found missing metadata checks, before any evaluation occurred. Run002 verifies training metadata, input identities and source/checkpoint identities before loading evaluation arrays. Both runs retain all 225 optimizer outcomes. `INDEPENDENT_REVIEW.json` records the separate audit.

AT and AVT heads are fitted separately using the same nested audio/text probabilities. Masking the video probability in the seven-feature polynomial map produces duplicate AT columns and therefore changes effective regularization; this is not an equal-capacity proof of video necessity. Bootstrap intervals are paired descriptive summaries over six historically exposed development actors. Video shuffling is a fixed mechanism diagnostic and is not another independent dataset.

`inputs/results/retention001` and `inputs/dev/addressing_train001` are small original checkpoints selectively restored for sibling follow-up experiments. `SHARED_CHECKPOINT_IDENTITY.json` binds them to the original complete evidence. They are not video training inputs.
