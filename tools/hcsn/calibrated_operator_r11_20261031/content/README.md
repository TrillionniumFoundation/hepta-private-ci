# R11 causal raw-symbol content experiment

This study trains every recurrent and readout weight using exact NumPy BPTT.
Five arms have exactly 782 trainable weights, 12 hidden coordinates, and one
validation-fitted scalar temperature each: ordinary single gate, ordinary dual
gate, locally matched dual gate, analytic single gate, and analytic dual gate.
Equal parameter counts do not establish equality of the full function classes.
All arms use the same initialization seed, minibatch index sequence, raw symbols,
elapsed times, marker/query observations, number of updates and validation rules.

## What the analytic gates mean

For a Brownian process starting at zero, constant drift `mu`, constant positive
noise `sigma`, horizon `dt` and positive barrier `B`, `hit` implements

`Phi((mu*dt-B)/(sigma*sqrt(dt))) + exp(2*mu*B/sigma**2)*Phi((-mu*dt-B)/(sigma*sqrt(dt)))`.

The two marginal event probabilities are `up=hit(mu,sigma,dt)` and
`down=hit(-mu,sigma,dt)`, with `mu=.7*tanh(a)` and
`sigma=.35+.45*sigmoid(b)`. They can overlap: a path can touch both faces.
They are not a normalized pair of competing outcomes, equity and put prices,
or an implemented full He--Xiong rollover model. Each recurrent step uses a new
frozen-window operator to gate content; this is not an exact continuous path
with reset/refractory propagation. Those dynamics are a separate R11 workstream.

The matched-slope control matches BOTH channel values and BOTH partial derivatives
with respect to `a,b` at `(0,0)` for each actual `dt`. It is a local comparison;
it does not match the entire nonlinear function. The ordinary dual control uses
independent sigmoid gates. The single controls devote the second projection to
candidate modulation, so all parameter blocks remain useful rather than being
counted as unused padding. Consequently the single/dual comparison includes this
explicit capacity reallocation; post-training channel removal is only a causal
diagnostic and cannot prove the removed channel is necessary after retraining.

Both analytic outputs are deterministic features of the same inputs. They add
an inductive bias, not new information unavailable to the controls.

## Data, chronology and decisions

The two tasks are deliberately synthetic: remember a marked raw symbol through
distractors, and infer a binary label from a causal noisy symbol sequence.
No supplied Bayesian posterior, hidden label, future feature statistic, or future
observation enters `Model.step` or `encode_prefix`. The retained-label task can
answer only at its observed query. The evidence task really stops consuming
frames at its selected confidence threshold. It does not implement the separate
two-job native Bellman owner's STOP/SKIP/READ/FIRE decisions.

Every model is trained on TRAIN, selected and calibrated on VALIDATION. All 50
model checkpoints are hashed into `FREEZE.json` before test or OOD RNGs/arrays
are created. OOD includes longer 72-frame sequences and shifted timing/noise.
Protocol and training source identities are registered before training. Raw
datasets, all update traces, final/selected checkpoints, validation decisions,
per-episode heldout predictions/actions and numerical checks are retained.
The same frozen model additionally receives channel-removal interventions; no
heldout result changes any model, temperature or action threshold.

## Cost and interpretation

The primary budget is equal optimizer updates, not equal CPU. Affine FLOPs are
an explicit estimate; special functions, memory, Adam and I/O are absent from
that estimate but included in measured CPU/wall work. Development, validation,
calibration, executed inference and total study process cost are reported.
Inference timing is active-row batch throughput, not isolated request latency.
No GPU or energy measurement is claimed. The declared net utility prices CPU
at 0.001 per second and amortizes each model's development over 10,000 queries;
the price and denominator are protocol choices, not measured deployment economics.
Shared synthetic generation and post-hoc scoring are included in total process
cost and reported separately from operational per-query utility.

Five seed clusters support paired descriptive bootstrap intervals. The nominal
24-contrast adjusted tail uses only about four of 2,000 bootstrap draws, so it
is not an exact finite-sample familywise guarantee. Results cannot be extrapolated
to real media, foundation-model scale, deployed Hepta or biological neurons.

## Prior real-media evidence considered

R10's `av/PROTOCOL.json` at commit
`4f96f7a91895ba3aed12539d323b62f6705bbb36`, blob
`3d7cdc54b967f0bd0a9f3d07185419215e75ef5b`, describes offline CREMA-D
low-level features and explicitly excludes causal media streaming. It also says
the historical test cohort was already known. This study therefore does not
relabel that corpus as fresh raw-media confirmation. R10's independent NumPy
BPTT model (`av/models.py`, blob `f55a734c3c0bd7ec4323cdddda0821079110e732`)
was reviewed as an implementation reference; the present recurrence and
drift/variance derivatives are newly implemented and independently checked.

## Reproduce

From the repository root:

```bash
python tools/hcsn/calibrated_operator_r11_20261031/content/study.py --out /tmp/r11-content-new-run
python tools/hcsn/calibrated_operator_r11_20261031/content/summarize.py /tmp/r11-content-new-run
```

Outputs are exclusive-create and cannot silently overwrite prior runs.
`models.encode_prefix` is the integration interface for previously observed
eight-field frames; it never accepts an externally supplied action or label.

The delivered run retains aggregate JSON directly and archives original datasets,
checkpoints and per-example traces. `evidence/confirmation_01/INDEX.json` maps
each original member path to a bounded deterministic archive, byte count and
SHA256. Restore all exact original bytes into a fresh directory before inspecting
an individual archived member or replaying statistics:

```bash
python tools/hcsn/calibrated_operator_r11_20261031/content/restore_evidence.py restore tools/hcsn/calibrated_operator_r11_20261031/content/evidence/confirmation_01 --destination /tmp/r11-content-restored
python tools/hcsn/calibrated_operator_r11_20261031/content/summarize.py /tmp/r11-content-restored --result-directory /tmp/r11-content-recomputed
```
