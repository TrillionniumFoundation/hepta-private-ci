# Repeated input identity and previously unused syntax: a bounded stress experiment

Parent: `b31ffdf3e2268cee9431cccac1f159c954b57b12`, Draft PR #1550.
This is an additive profile of `fbsde_study.py`, not another scientific reviewer,
production owner or new pretrained model. All previous profiles and controls remain.

## Same Head is not enough to model identical repeated inputs

The prior mixture preserves one latent member per story, but still resamples a
categorical event outcome within that member at every step. The new model assigns
ONE latent categorical interpretation to each declared full input key. A repeated
key uses the same interpretation again, while its state operation still executes
in its original chronological position. With group map k(i):

    p(o) = sum_m w_m product_k q_mk(z_k), subject to o_i = z_k(i).

An observation likelihood is included once per distinct key, not once per alias.
Inconsistent observations of aliases reject; a revealed key is not proposed for
another paid check. Member posterior weights remain shared globally and are
recomputed from the original prior. No branch chooses its own hidden member.

Key identity includes FULL original instruction text, ordered actor coordinates,
model, calibration, source, scope and generation. Equal embeddings, output scores,
or approximate string similarity cannot justify it. The invariant is valid only
for the explicit pure-swap grammar in this experiment. It does not allow reordering
operations or merging stateful actions in general. Per-member laws of aliases must
match exactly. There is still an independence assumption between distinct keys and
an uncalibrated three-member prior; unknown shared Encoder errors remain possible.

The existing finite BSDE planner only gains an available-event port, whose original
implementation exposes the same prior event set. Existing cost=.02, total horizon
2, 20,000 planning nodes and 100ms process-CPU planning cap remain. The tied model
also limits complete latent assignments to 8,192 before allocation; no outcome is
silently pruned. Assignment/holder compilation is separately measured model
preparation, NOT free work or part of the planner-only timer. Neither timer is a
whole-request hard deadline. Original proposal admission is likewise unchanged.

## New challenge, not another run of a solved public benchmark

Three 2,073-parameter gates use the previous architecture, simulator-only 720-row
training recipe, seeds, 160 AdamW steps and learning rate. They share one frozen
128-dimensional lexical frontend; no large Encoder is copied. Temperature selection
uses 72 separate three-actor simulator events, never target-family wording. This
profile does NOT silently substitute lexical vectors for mmBERT: it is explicitly
lexical only. No new pretrained forward or BBH benchmark score is claimed.

Six new controlled English templates mention both exchange participants AND a
nonparticipant (watcher, negation or an explicit exclusion). None is in the fitting
or calibration generator. The public design, seeds, costs and full family inventory
are written before predictions. All 144 generated stories remain in the denominator,
with 2..7 steps and repeated source instructions; no examples are selected because
models disagree or fail. A separate explicit interpreter supplies source operations
only after a verification choice. The surrounding process already parses the full
story, so fewer modeled checks are not physical parsing savings. Outputs are sealed
before final-answer scoring, not before the permitted source-operation verifier.

The ten matched arms retain single/product/shared/tied no-check, shared/tied one-
and two-step control, verify-all and exact reverse. Their observations and learned
probabilities are shared; the tied arm adds the declared same-input joint constraint.
The cheap exact reverse needs no neural prediction and stays in the results.

## First complete result and its limits

First complete execution: 144 tasks x 10 arms = 1,440 outputs; 648 evaluation events.
Shared-member two-step: 114 correct / 132 answered, 72 checks. Tied two-step: 127
correct / 144 answered, 64 checks. But tied MYOPIC also gets 127 correct, answers
143 with 62 checks and higher modeled utility (.76222 versus .755). Exact reverse
gets all 144 correct with no charged checks and less measured controller CPU.
This is NOT a new two-step or NDU superiority result.

All three heads have the SAME top pair on every event, and are jointly wrong on
216/648 events. Only 36 distinct original event strings occur, so those repetitions
are not independent errors or sample-size support. Agreement is not accuracy, and
in-distribution temperature calibration did not certify this syntax shift. The
syntax and semantics are generated, not independently authored real-world tasks;
the source interpreter is hand-coded. No general language or production claim.

First result files remain immutable. Subsequent audit/test executions do not count
as new held-out observations. An independent auditor (no planner or Torch import)
uses forward holder matrices and complete tied-variable enumeration, reconstructs
source semantics, temperatures, conditional decisions, probabilities, decoded
answers, and measured costs. Per-arm costs exclude some common preparation and
are NOT standalone lifecycle totals. Riccati remains a separate numerical solver.

```sh
PYTHONPATH=qualification/neuron-stem python qualification/neuron-stem/fbsde_study.py \
  --profile input_tied_challenge_v1 --output /new/research-evidence
PYTHONPATH=qualification/neuron-stem python -m unittest test_fbsde_tracking_tied \
  fbsde_tracking_tied_tensor_checks -v
```
