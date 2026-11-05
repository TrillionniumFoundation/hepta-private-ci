# Registered real-parameter training wiring run

This run performs two separately supervised updates on each real generator,
then executes one fixed dual schedule with the resulting adapters. It uses the
single public input already preserved by run 41972148925. The caption is a
declared training target; the image target is the source photo itself.
There is no held-out source, learned controller or joint-return objective.
Photo reconstruction training does not establish learning to draw diagrams.

The plan and two training-only manifests are saved before any update. Both
trainers must return admitted checkpoints. For the image trainer this includes
its explicit qualification flag. Failure cannot silently fall back to an
unadapted generator, and a cancellation prevents starting the other trainer.
Each trainer verifies changed neural parameters, unchanged base parameters
and identical same-input outputs after checkpoint save/reload.

The fixed inference schedule is perceive/text/draft/verify/STOP. Its backend
reattaches the correct verified adapter every time a model family reloads,
including VLM/SD/VLM. Each new hash/load/attach occurs inside the corresponding
metered runtime action. A repeated activation of the same resident family
does not install duplicate hooks. Identity distinguishes frozen base weights
from the active learned residuals. The inference request contains no training
target; the controller still receives only its existing public View.

The dedicated workflow records inclusive physical-command CPU/wall receipts
for installation, tests, acquisition and the whole training process. The
process, trainer and action receipts are nested and must not be added together.
Original failures and partial artifacts remain; model weights are excluded.
Meter startup, final receipt writing, external logging and energy remain
explicit outer/unknown costs. This is not a production net-utility estimate.

`run_training.py` exits successfully only if both training/checkpoint procedures
complete and the adapted dual runtime mechanically delivers its pair. That
exit code never supplies semantic acceptance. Original poor outputs and the
separate input-conditioning diagnostic are retained unchanged. The next
factorial protocol is described in [NEXT_FACTORIAL.md](NEXT_FACTORIAL.md).
