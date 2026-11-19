# E12 neural continuation warm starts — mathematical study, DENY_ALL

**Status:** Draft / shadow only / NO-GO for online deployment. Stacked after the
exact E12 nonlinear finite-tree solver and #2508 independent local-Cell audits.
This adds **actual fitted small neural weights**, not another frozen/tabular
critic, but it does **not** fit a real pretrained Encoder or solve a general
continuous-time NDU FBSDE. No objective/authority/FinalUse/Neuron production
API, policy, existing CI gate or native shared weights are modified.

## Exact hypothesis

For the registered finite stochastic E12 law only,

```
X_{k+1}=X_k + a*h*phi(Y_k) + sigma*m_{k+1}
(1+lambda*h)*Y_k = E[Y_{k+1}|F_k] + beta*h*phi(X_k)
Y_T=g*phi(X_T); phi(x)=x/(1+x*x)
```

learn a context-conditional initializer `V_eta(x0,public-prefix,law)` using
**train-only whole-tree E12 teacher solutions**, then warm-start the original
oracle-free local Cell sweeps. The field is a `10 -> 12 tanh -> tanh` trainable
readout with **145 actual FP64 scalars**; frozen at inference. A 10-feature
bounded representation uses root state, past public branch signs, known
coefficients and depth, **never a future random sign or held-out label**.

The zero, constant (one scalar), linear (11 scalars), and neural (145 scalars)
arms have the same `1/10000` *global* contraction-bound requirement, capped
at 24 local sweeps. The direct a=0 BSDE/Bellman one-map algebraic baseline
remains the cheaper correct option on that registered subproblem. Coupled
a=1/3 single-map controls cannot claim success without their actual residual.
A warm solution must NOT inherit E12's independent **zero-start** replay
receipt: the new reviewer replays from the exact disclosed frozen initial Y,
checks every nonlinear prefix-state X, interior/terminal Y, conditionally
centered two-point Z, stopping step and `||Y-F(Y)||∞/(1-q)`. No locally
reset continuation, forged terminal error or substituted field grants a pass.

## Fixed research source groups and accounting

- Training: 19 distinct `x0` sources × 6 laws, 114 original exact E12 teacher
  solves producing 418 actual per-prefix targets. Fixed 80 SGD epochs, seed
  1729, rate 0.018; both linear/neural see the same examples/epochs.
- Calibration: 8 disjoint synthetic x0 groups, **reserved but not used for
  choosing weights or admission**; not a claim about calibrated confidence.
- Held study: 10 independent x0 IDs (not independent real-world source
  families) × 6 laws, 60 scenarios × 4 policies = 240 fully evaluated
  mathematical runs. The held x0 roster is frozen in source before blinded
  model execution, but this is not a preregistered real future-time trial.
- Three-stage process: `train` writes create-only frozen head/digest and
  actual teacher + SGD CPU; `blind` opens no held solutions and seals all
  240 Y/X/Z runs; a separate `score` process opens the original held teacher
  **after** verifying raw train/blind SHA, re-fits coefficients deterministically,
  independently replays all local stochastic trajectories and reports grouped
  work/cost/error. The re-fit shares the original training algorithm and is
  **not** independent optimizer verification. SHA is not an owner signature.
- Recorded CPU times are actual **self-observed local/runner process times**, not
  target-host attestation or matched end-to-end service latency. Inference
  includes field evaluation; training and teacher labeling are charged in the
  full-panel cost. No GPU, energy, model load, pretraining or token generation.

## Actual initial authoring-container observations (Python 3.13)

| Arm | Held Cell updates | Whole-panel inclusive CPU vs training |
|---|---:|---|
| Zero | 1,140 | Low computation; no fitting |
| Constant | 1,140 | Fitted teacher + prediction overhead |
| Linear | 1,084 | Real per-row SGD and head predictions |
| Neural | **1,048** | Real 145-parameter SGD; much higher total CPU |

On this one local trial, neural reduces local Cell updates **92/1,140 = 8.07%**
but its one-panel train+teacher+inference CPU is much larger than zero.
Original reviewers must reproduce values on the exact GitHub source SHA.
The 30 uncoupled held cases have a cheaper certified **one-map direct**
solution, with just 220 mathematical Cell updates across those cases.
The 30 coupled held cases' cheap zero-start one-map remains uncertified at
the registered threshold. Saved Cell counts are **not** equal model FLOPs,
GPU throughput, natural reasoning quality, lower tail latency, or a 10T model.

**Decision: NO_GO for deployment or claimed cost-adjusted general reasoning
advantage.** Mathematical warm-start work reduction motivates further study,
but pays back neither fitting nor teacher cost in this observed evaluation.
No source issuer/observer signature, natural labels, held future windows,
independent learned neural coefficient identification, real Stem/Reader/Decoder,
or physically shared 1,024/4,096 Cell GPU workload is present.

## Running the bounded study

```sh
ROOT=qualification/shared-stem-system2-architecture
export PYTHONPATH="$ROOT"
python -m unittest discover -s "$ROOT" -p 'test_e12_*.py' -v
python -O -m unittest discover -s "$ROOT" -p 'test_e12_*.py' -v
mkdir -p /tmp/hepta-e12-field
python "$ROOT/e12_continuation_study.py" train --output /tmp/hepta-e12-field/train.json
TRAIN=$(sha256sum /tmp/hepta-e12-field/train.json | cut -d' ' -f1)
python "$ROOT/e12_continuation_study.py" blind --train /tmp/hepta-e12-field/train.json \
  --train-sha256 "$TRAIN" --output /tmp/hepta-e12-field/blind.json
BLIND=$(sha256sum /tmp/hepta-e12-field/blind.json | cut -d' ' -f1)
python "$ROOT/e12_continuation_study.py" score --train /tmp/hepta-e12-field/train.json \
  --train-sha256 "$TRAIN" --blind /tmp/hepta-e12-field/blind.json \
  --blind-sha256 "$BLIND" --output /tmp/hepta-e12-field/scored.json
```

This is a **research-only numerical tool**. Exact head and synthetic-merge
GitHub Actions plus unchanged `blocking-ci` and Architecture are separately
required and are not declared successful by local tests. Any future genuine
System2/Cell/Stem admission additionally requires a strong Reader, genuine
natural held outcomes, equal *full-life-cycle* cost and existing governance.
