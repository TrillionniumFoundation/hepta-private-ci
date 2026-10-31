# First-choice value consumption

This additive experiment asks whether the fitted value heads affect an actual
decision and delivered utility. It leaves all frozen top-level v3 sources and
their results unchanged. It does not introduce repeated replanning: after one
selected action, every nonterminal branch uses the original sampled actor.

## Frozen development protocol

Before reading outcomes, run 16 fresh synthetic sources from
`joint-v3-critic-choice.fresh-analysis.20261030`, four independent future draws,
and these four arms (256 actual continuations):

1. Original sampled actor from the encoder boundary.
2. Original critic chooses the first action; original actor continues.
3. Independently calibrated critic chooses the first action; original actor
   continues.
4. Immediate STOP.

The original and calibrated checkpoints must have identical content and actor
tensors and identical generation configurations. Generation always executes the
original model. The calibrated checkpoint supplies only the external first-choice
value estimates; it never substitutes generator weights during an episode.

For each source, encode once and clone the same public prefix, exact budget and
already incurred cost. A future tape is paired across all arms for each draw.
The actor and emission streams are separate. Forced first choices do not consume
an actor draw; this is a declared common-initial-tape coupling, not a claim that
every later actor event uses the same random number across unequal trajectories.

## Approximate decision and actual costs

Each learned consumer evaluates all legal first actions using public state and
the registered service tariff plus a learned log conditional moment. STOP uses
the pre-STOP delivery head, whose target already includes STOP and delivery.
The chosen action minimizes the approximate log moment. Neither target content
nor the outcome observer is available to this rule.

Candidate evaluation is real computation. Its CPU/wall cost is appended to the
budget ledger before the selected action is dispatched; this creates a genuine
post-planning budget difference. Legality is checked again by the existing
runtime. Complete returns include planning, original generation, actual codecs,
readback/observer, runtime seal, and measured caller-close gaps. The final
consumer receipt write remains reported outer work. Cold loading and the prior
calibration training are reported separately, not amortized into these per-request
comparisons. No production latency or monetary cost is claimed.

Source-cluster bootstrap comparisons use CE(candidate) minus CE(reference), with
the unchanged gamma=2, 1,000 replicates, and actor/STOP/original-critic references.
The calibrated-versus-original-critic comparison directly measures the effect
of calibration on the first decision under the same continuing actor. Arm order is
balanced by a deterministic cyclic rotation. All failures and all arms remain
in the result. This new source cohort is development evidence; it consumes no
reserved confirmation data and selects no further checkpoint or hyperparameter.

## Meaning of a result

A better calibration score does not imply a better action ranking. Even an exact
first-action value under the continuing actor would not solve a new repeated-
planning policy. A positive result here would establish only a bounded empirical
benefit of the first-choice rule on this fresh mechanism cohort after its actual
planning cost. It would not establish general NDU semantics, natural language or
media quality, a free-boundary optimum, or global optimality.

## Reproduction

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.critic_choice.run --original-checkpoint MODEL.pt --calibrated-checkpoint MODEL_CALIBRATED.pt --output critic-choice-study
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.critic_choice.test_run
```

The runner writes `FROZEN_PROTOCOL.json` before accessing cohort outcomes and
retains every actual media bundle, independent numerical readback, ledger and
selected action. `RESULT.json` reports all four arms and both reference
comparisons, with qualification flags left false.
