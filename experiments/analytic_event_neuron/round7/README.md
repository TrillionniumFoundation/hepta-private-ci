# Round 7: joint event-cell and task-value research

This is a research implementation of a **single finite-state event cell with a
dense content encoder and action-value controller**. The voltage grid has 15
active nodes and two refractory states; those nodes are not 15 spiking neurons.

The work continues Round 6 at
`bf88335edc41d40d57d8e84716dd1d2e8cd13a68`. It adds physical event-state contracts
within the stated discrete models, joint learning through reset and recovery,
and a finite closed-loop task with real READ / WAIT / REPAIR / STOP actions.

**Read [REPORT.md](REPORT.md) for the results and promotion decision.**
The complete reproduction workflow is in [REPRODUCE.md](REPRODUCE.md).

## What is registered

The pre-confirmation seal is [FROZEN_MANIFEST.json](FROZEN_MANIFEST.json):

```text
UTC:    2026-10-31T02:23:47.523187+00:00
SHA256: 3cda25b5fc17774e624d590679267066b51a9246072801c53453ee964b2202f0
```

The inputs include 60 registered checkpoints, five fit seeds, 45 passing
implementation tests, and a fixed 108,800-trajectory evaluation. The frozen
protocol and all 60 weights were persisted in Git before confirmation at
`e5202c923bbd4dc9f4879d6a95f2baec788eebdf`.

Five additional temperature-control fits were rejected before confirmation
because their implementation failed probability-mass checks. They and their
costs remain in the evidence. Explicit checkpoint registration prevents their
use even if retained copies exist in the original output directory.

## Scientific contracts

| Component | Definition and source |
|---|---|
| Continuous distribution | Gaussian OU transitions projected onto a finite bounded grid; no physical-model spike events. See [DYNAMICS.md](DYNAMICS.md). |
| Clocked events | Tick-end upper/lower threshold checks, explicit reset law and tick-end recovery. |
| First-passage events | Exact transition probabilities for the specified absorbing finite CTMC; numerical approximation to continuous OU first passage. |
| Content and dynamics learning | Mass-weighted supervised initialization followed by differentiable exact finite joint-state soft-policy return and auxiliary critics. |
| Independent task reference | Public-state DP with an independently implemented observation/transition law. See [TASK.md](TASK.md). |
| Main deployment | One sampled latent state and greedy legal action; mean-state, Q24 and soft-action deployments are separate controls. |
| Statistical comparison | Registered paired A/B/C/D contrasts, complete identity-grid validation, fit-cluster bootstrap and seed-level sensitivity. See [PROTOCOL.json](PROTOCOL.json). |
| Files and native adapter | Actual broker IO/readback and historical native adapter calls. The Round 7 cell is not installed in the original native kernel. |

Full scope and limitations are in [CONTRACT.md](CONTRACT.md).

## Code map

- `dynamics.py`, `temperature.py`: transition/event/reset/recovery laws.
- `task.py`, `oracle.py`: actual finite evidence task and independent DP.
- `model.py`, `learning.py`, `joint_control.py`: content representation and two-stage joint training.
- `policy.py`, `study.py`, `statistics.py`: deployment, paired evaluation and inference.
- `audits.py`, `broker.py`, `native_bridge.py`: conditional values, state persistence and actual IO.
- `numerical_audit.py`, `resolution_transfer.py`, `profile.py`: numerical accuracy, learned-parameter grid sensitivity and component costs.
- `freeze.py`, `artifact_bundle.py`: input identity and complete evidence preservation.

## Evidence interpretation

Implementation correctness and continuous-model accuracy are different claims.
The numerical accuracy audit retains failed gates, including low-noise
artificial diffusion, fixed-grid small-time-step behavior and non-Gaussian
misspecification. Task reward stability does not repair those discrepancies.

The value heads output expected task returns, not calibrated probabilities of
success. Task costs, declared compute/event proxy prices, measured CPU/wall
time, serialized packet sizes and actual broker transport are reported
separately. No hardware-energy saving is inferred from event counts.

The registered experiment uses the same public information, data and update
schedule across models. It does not claim equal CPU-second training budgets.
The task is a known finite simulator with artifact execution, not an open
document-understanding benchmark or a production Hepta deployment.
