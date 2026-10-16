# Actual Head investment on frozen historical Reader outputs

Research-only / DENY_ALL. Parent #2319 at
`778bb8a32e725b00db59e16cdcdc38fd777ae964`. The original exact Merton panel and
FBSDE obstruction tests remain unchanged. This is a next-step parameter-learning
experiment, not a production Neuron replacement or a continuous FBSDE solver.

## Source and scope

`material.LOCKS` pins four original GitHub Actions ZIP archives: original
ModernBERT/four-Reader native-answer logits, two complementary original-human
training-fold materials, and the earlier independently implemented human score.
All archive bytes must match before parsing. Label overlaps must agree. The
original-human parquet SHA is retained; the parquet is NOT freshly downloaded by
this experiment. Reconstructed labels come from archived HUMAN training rows,
not scores, a model-generated teacher, or synthetic labels. The original Reader
baseline is checked against the archived human scorer.

The only data are 4 historical source passages, 8 questions and 33 dependent
answer candidates. There are no new future sources. Multiple folds, reuse
horizons, training candidates and controller arms DO NOT increase this source
count. All results are retrospective, same-family diagnostics and underpowered.

## Real learning, with fixed prediction and selection targets

Inputs are four original logit margins, centered WITHIN each complete native
question without labels. Each training partition alone fits four RMS scales.
A five-parameter residual Head (four weights and a bias) is added to the frozen
mean-pool-query margin. All weights initialize to zero. Zero steps therefore
match the frozen Reader exactly. Full-batch SGD actually updates five float64
parameters at 8, 32 or 128 steps with learning rate 0.1 and question-balanced
two-class Brier loss. The optimizer never updates the source Encoder or original
Readers. Cached logits are not new pretrained inference, and a residual readout
is not the original Neuron runtime Head.

Each outer fold holds out one entire passage. Three inner leave-one-passage-out
calibration folds use only the other three passages: two for fitting and one for
calibration. Selected steps are then refitted on the three outer-training
passages. Heldout labels never enter the worker's fold files; the separate
post-seal auditor obtains them from original archived human materials. The
coordinator has all labels to construct the views; this is data-flow isolation,
not an OS sandbox or independently signed custody protocol.

Six controls are no update, fixed 32 steps, budget-neutral, fixed-risk,
discrete NDU-inspired outcome-driven preference, and an ordinary augmented-state
reference using the same preference profile. Every search controller physically
executes its own pilot bank; no fitted candidate or selection cost is treated as
free. Selection uses COMPLETE-QUESTION success, never candidate accuracy/Brier
as a substitute. The one-decision recursive profile is
`(1-alpha) mean(passage_success) + alpha min(passage_success)`.
The dynamic preference starts at 1/4 and uses only frozen-control observed inner
calibration question outcomes, decreasing by 1/8 for success or increasing by
1/4 for failure, clipped to [0,1/2]. It is a fixed bounded rule, not neural
preference training. Every choice must equal ordinary augmented enumeration
under the SAME objective. Different risk objectives are not algorithmic wins.

## Cost and horizon interpretation

Reuse demands 1, 8 and 64 are declared planning scenarios, not actual new future
tasks. Only original heldout questions are scored; they are not multiplied by
reuse demand in reported empirical quality. The fixed utility price is 0.001
success units per CPU millisecond, NOT dollars and not an estimated human
preference. Final-refit cost is forecast by row-exposure scaling of measured
pilot CPU; inference quote is measured pilot prediction/scoring CPU per question.
Both are explicitly estimates for the investment choice, not observations of
future serving. CPU jitter can affect ties; there is no certified cost interval.

The entire executed pilot bank is a sunk cost and stays charged even if the
selector chooses zero steps. Final training, selection, scoring and inference
are separately metered within an inclusive lifecycle CPU/wall observation.
No-update runs zero optimizer steps; fixed-32 does not pay a fictitious search.
Timing includes Python and measurement overhead. Current preprocessing and
independent verification have separate cost receipts. Historical Encoder/Reader
cost is retained separately because hardware/time differs; it is not combined
with current CPU to claim fresh online service cost. Network acquisition,
energy, p99 and production memory are unqualified. No whole-lifecycle efficiency
or independent hardware observer is claimed.

## Replay and acceptance

`audit_real.py` independently implements SGD, prediction, full-question scoring,
preference updates and exact rational selection values. It imports the shared
specification/shape constants but does not call the learner's fit, predict,
select, or alpha update. It reconstructs fold material from pinned original
archives, verifies each pilot and final weight/trace and all calibration/heldout
predictions, checks all incurred steps and phase containment, and scores original
human labels only after a seal exists. Both implementations have the same
author. Timing receipts are not authenticated by numerical replay.

Passing arithmetic/tests cannot establish real reasoning gain, new-domain
learning, Encoder improvement, policy identifiability, continuous FBSDE validity,
world-model learning, production readiness or model promotion. Retain original
Reader-adequacy failures. A candidate-level change without complete-question
improvement is a failed primary gate, not a win.

## Reproduce

Use Python 3.13, standard library only. Put the four pinned ZIPs in `$ASSETS`
using numeric artifact IDs as filenames, then:

```sh
D=experiments/ndu_tree_fbsde_gates/merton/real_head
export HEPTA_MERTON_ASSETS="$ASSETS"
python -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python -O -W error::ResourceWarning -m unittest discover -s "$D" -p 'test_*.py' -v
python "$D/material.py" --reader "$ASSETS/11946621518.zip" \
 --labels0 "$ASSETS/11949305579.zip" --labels1 "$ASSETS/11949100961.zip" \
 --human-score "$ASSETS/11953241456.zip" --output /tmp/merton-real-inputs
python "$D/learning.py" --material /tmp/merton-real-inputs --output /tmp/merton-real-run
python "$D/audit_real.py" --reader "$ASSETS/11946621518.zip" \
 --labels0 "$ASSETS/11949305579.zip" --labels1 "$ASSETS/11949100961.zip" \
 --human-score "$ASSETS/11953241456.zip" --material /tmp/merton-real-inputs \
 --run /tmp/merton-real-run --output /tmp/merton-real-score.json
```

Outputs are create-only. Use fresh paths for a new run. The worker does not open
`scorer-labels.json` or source ZIPs. This isolated cached-input experiment must
not bypass `blocking-ci`, Architecture, original runtime writers, FinalUse or
independent future-source evaluation. No main merge or production activation.
