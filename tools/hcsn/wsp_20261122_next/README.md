# Value-sensitive weight programming

This research module compares a gradient-free Bellman rank-one edit program with
projected gradient training on the same complete finite own-law stochastic-policy
value. The deployable hard-policy value is evaluated separately. The editable
coordinates, original radius, information and proposal/CPU caps are fixed before
any new candidate quality is observed. See `DESIGN.md` and `PROTOCOL_FROZEN.json`.

## Inputs and numerical admission

Provide the exact `input_bundle` described by `PROTOCOL_FROZEN.json` through the
explicit `--inputs` argument. Input paths inside the protocol are relative. Every
read checks the expected byte length and SHA-256. `DEPENDENCY_PROVENANCE.json`
records the original versions of the unchanged scientific helpers in `vendor`
and `semantic`.

The recorded numerical environment must match: Python executable, NumPy binary
and dispatch, one CPU affinity core, one BLAS thread, RN rounding and gradual
underflow. This package is not a complete OS image. Moving the input bytes is
supported; changing the numerical implementation requires separately recorded
qualification rather than silently changing the frozen protocol.

The direct editor receives the same complete simulator information as the
gradient baseline. Own-law terminal posteriors, transition probabilities and
action values are not future-market labels. Diagnostic oracle scores are not
model weights.

## Run the fixed stages

Use a new, empty run directory. Each attempt and artifact is create-only.
The supervisor accounts for the complete Python child lifetime and its own CPU.
It enforces the frozen OS CPU, wall and address-space limits.

```bash
python3 -B supervise.py generation \
  --protocol PROTOCOL_FROZEN.json --inputs input_bundle --run-root run \
  --attempt run/generation_attempt001

python3 -B supervise.py selection \
  --protocol PROTOCOL_FROZEN.json --inputs input_bundle --run-root run \
  --attempt run/selection_attempt001 --previous run/generation_attempt001/output

python3 -B supervise.py confirmation \
  --protocol PROTOCOL_FROZEN.json --inputs input_bundle --run-root run \
  --attempt run/confirmation_attempt001 --previous run/selection_attempt001/output

python3 -B supervise.py verification \
  --protocol PROTOCOL_FROZEN.json --inputs input_bundle --run-root run \
  --attempt run/verification_attempt001
```

Selection entropy is drawn only after the complete candidate seal and actual
model bytes are checked. Confirmation entropy is drawn only after the selection
seal and its candidates are checked. A collision, incomplete graph, resource
failure or unfavorable world is never replaced. A failed optimizer family maps
to KEEP, with its partial trajectory and all incurred cost retained.

## Evidence to inspect

- `generation_attempt001/output/CANDIDATES_FROZEN.json`: immutable primary and
  diagnostic model identities, before fresh selection schedules.
- `generation_attempt001/output/generation/`: every proposal, rejected candidate,
  objective count, gradient count and actual resource use.
- `generation_attempt001/output/diagnostics/`: complete GEN-only continuation,
  Belief and joint oracle interventions.
- `selection_attempt001/output/SELECTION_FROZEN.json`: deterministic per-family
  KEEP/retention decisions before fresh confirmation schedules.
- `confirmation_attempt001/output/RESULTS.json`: all six contrasts, checkpoint
  pairing units and the predeclared improvement rule.
- `verification_attempt001/output/RESULTS.json`: independent hard-policy DP,
  source/parameter/radius checks, rebuilt new worlds/features and choice replay.
- Every `PROCESS.json`: complete child and supervisor CPU, wall, peak RSS,
  limits, exact protocol and executable source identities.

The prior confirmation set stays sealed. New confirmation is also never reused
to tune the current candidate family. Publishing evidence does not adopt a
model into a production service.
