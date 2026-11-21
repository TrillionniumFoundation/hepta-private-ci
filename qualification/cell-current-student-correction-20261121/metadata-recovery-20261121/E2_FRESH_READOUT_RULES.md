# Interpretation rules for the prospective E2 fresh panel

This note adds no execution allowance and changes no published acquisition,
training, inference, or native-verification rule. It records how the existing
bounded successor must be interpreted before any new model score is observed.

## Experimental units and comparison

The published fresh scope has four qualified tasks from four distinct GitHub
owner namespaces, two retained student lineages, and three arms per lineage:
frozen parent, bounded retrieval, and corrected child. Its 24 model slots are
not 24 independent tasks. The two student lineages use different prior training
evidence; they are not independent random-seed repeats of one training method.
GitHub namespaces also do not establish independent human contributors.

For each lineage and arm, retain the full four-task outcome vector. Compare
the corrected child with its own parent on the same task, request policy,
tokenizer, input and output limits, generation parameters, answer codec, and
native verifier. Report paired gains and losses, all refusals, and exact case
identities. Keep the retrieval arm separate; it tests a different use of the
same permitted A evidence and does not modify weights.

An admitted evaluation slot that fails output admission or native verification
remains in the declared task denominator. An acquisition refusal is a material
selection outcome, not a model failure, and cannot be replaced outside the
published fixed ordering and limits. A refused four-source panel produces no
valid complete-panel model comparison. An unconfirmed execution or cleanup is
unknown and cannot be silently recorded as either a pass or a completed zero.

Report paired binary outcomes as a four-row table, alongside the raw count.
Do not treat native pytest cases, repeated helper invocations, inference turns,
three arms, or two related students as extra independent sample size. With only
four task units, any apparent improvement is a small-panel signal, not a
precise population estimate or a demonstrated scaling law. For example, even
four gains and zero losses provide a two-sided exact sign-test p-value of
2 / 2**4 = 0.125 under the usual exchangeable-discordance null. This illustrative
calculation is not a precommitted claim of task sampling representativeness.

## Retention and policy boundaries

The new policy is one complete native chat request with 4,096 input tokens and
384 generated tokens. The old raw collection used a different multi-step
policy and larger 8,192 / 2,048 limits. New fresh-panel scores must not be
subtracted from the old exposed four-future-task scores as a causal effect.

A child can gain on one fresh task and lose a parent success on another; report
both. If the parent solves none of the fresh tasks, the panel provides no
positive preservation opportunities. Zero observed regressions in that case
does not demonstrate retention. This new panel alone also does not test
preservation of the old successful A behaviors. A broader old-capability
retention claim would require a separately fixed and authorized matched-policy
retention scope; this note does not create or spend that allowance.

The proposed training data currently contain one positive repair action per
selected failure state. Under this representation, final-only and all-positive
actions collapse to the same supervision. Do not label the same records as two
distinct trajectory methods or infer a trajectory advantage from that identity.

## Claim boundaries

The completed 56 old evaluation calls, the four exposed old future tasks, and
the two old 32-update fits remain closed. The new correction plan permits only
the existing two eight-update children. Model material must actually pass its
published integrity and engine checks before either child is described as
trained. New source contents remain unopened until the required completed
weight envelopes and selection publication exist.

A successful corrected-child result would not, by itself, establish Circuit
necessity, teacher complementarity, user-growth benefit, weight editing's
advantage over backpropagation, production adoption, or useful-work settlement.
The separate Q24 lifecycle fixture does not adopt these external E2 LoRA
weights. Integration requires its own exact-source and actual-weight evidence.

## Existing published sources

- Correction implementation and frozen data: PR #6833, executable source
  `dc3397c9e09e29861a0a4fe2267e8ef19e55db01`.
- Fresh contract: PR #6855, `53fc62303c3596c0b419e00d425d83462bd7cc7e`.
- Fresh native runtime: PR #6856, `068936febebd78fa55adfd7c825f5698df334d18`.
- Fresh acquisition and complete scope: PR #6857,
  `464131053063339ae4c6dbd254ee3c0a27b532b4`.

This interpretation was prepared with zero new encoded training records,
model calls, native evaluations, optimizer updates, or fresh source-content
reads in the prospective scope. Runtime-material and source-qualification
operations are separately metered engineering work.
