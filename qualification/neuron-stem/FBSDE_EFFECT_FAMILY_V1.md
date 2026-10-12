# Observation-driven effect-family revision and its limits

Parent `a4113e0898c5d8a3c4ca537ec4fa46bd33396302`, Draft PR #1550.
The existing study entry gains `effect_family_revision_v1`. Old role programs,
semantic Heads, Riccati solvers, thresholds, reviewer and native owners remain.
No neural weights or pretrained Encoder are run in this mechanism experiment.

## Why support unanimity can still be wrong

The old three-role family contains only transpositions. Repeating one unknown
transposition twice is identity under EVERY family member. Repeating a true
three-cycle twice is not identity. Thus a narrow-family unanimous answer can be
wrong without triggering any observation or numerical residual. This is a family
coverage error, not an incorrectly solved Bellman equation.

We now declare all six bijective role effects. Effect tuples are pullbacks:
`new_state[j] = old_state[effect[j]]`. Alpha-renaming reuses the original exact
name-normalized frames; no word, condition, punctuation or event is discarded.
One model binds a latent role permutation to a frame; a separately named model
assigns it per event. Neither tying assumption is a learned semantic theorem.
The old uniform-swap family is checked against the original RoleProgramBelief.

An observation port reveals the FULL realized event effect, including identity
or rotation, at that source execution's actual predecessor state. This is a
richer alphabet than the old pair-only verifier, but every new control uses the
same port. The simulator precomputes each arm's own execution outside the policy;
that work is measured separately even for unqueried effects. It is not an OS-
isolated authority, human observation, or proof of causal state sufficiency.

## Explicit revision, never conditioning zero mass or erasing evidence

Only a selected observation outside the current role support authorizes widening
that frame to all six permutations. This changes the model: it creates a NEW
identity/revision and uniform prior, then replays ALL observations. It is not a
posterior under the old zero-support law or the same global FBSDE solution.
Prior workspaces close before the new family is used. The original source/scope
binding and actual verification count remain; no budget reset or answer reuse.

The `expand_audit` control probes one instance and then another occurrence of
that frame when available. Contradictory realized effects explicitly invalidate
frame invariance. Its declared fallback creates a per-event model with all six
effects and replays both observations; ambiguity after two checks yields abstention.
Nonbijective effects, such as copying, are recorded and refused, not projected
onto the nearest swap. Invalid receipts fail with no returned action. Oversized
worlds reject before allocation; custom smaller world caps survive revisions.
The original two-check, 20,000-node and 100ms process-CPU allocation limits remain.
Model construction is a separately measured phase; each revision also has a
100ms post-call check. These checks are not preemptive real-time guarantees.

Crucially, two matching instances do NOT authenticate every unobserved instance.
A regression gives identical observed first/last effects but two possible middle
effects with different answers. Event-independent support covers that distinction
and abstains; shared-frame support can still be confidently wrong. Conditional on
correct observations and every actual effect being a permutation, an event-model
unanimous answer is correct because the actual effect sequence is in its product
support, even when effects depend on previous state. Those assumptions are not
established for arbitrary text, nonbijective effects or real verifiers.

## Fixed experiment, cheap controls and observed limits

Six declared strata (swap, identity, cycle, state-dependent, nonbijective, mixed),
all six name-role permutations, three queries and lengths 2/3/4 yield 324 cases.
There are nine controls, each with its own selected observation history: 2,916
outputs. Data generation does not consult predictions or errors. There are only
30 unique source instruction strings; this is generated mechanism stress, not
324 independently authored tasks, training generalization or a future window.

First completed run, correct/answered out of 54 per stratum:

| Stratum | Fixed swap two-step | Expand after first probe | Expand + invariance audit | Independent event probe |
| --- | ---: | ---: | ---: | ---: |
| Swap | 54/54 | 54/54 | 54/54 | 18/18 |
| Identity | 36/36 | 54/54 | 54/54 | 18/18 |
| Cycle | 0/36 | 54/54 | 54/54 | 18/18 |
| State-dependent | 34/42 | 46/54 | 42/42 | 18/18 |
| Nonbijective | 24/36 | 0/0 | 0/0 | 0/0 |
| Mixed frames | 0/0 | 18/18 | 18/18 | 18/18 |

Broad-frame two-step answers 36/36 mixed cases, vs 0/0 for the SAME-prior one-step
and 18/18 for a cheap broad-frame probe. But it costs more planner CPU. Starting
narrow and widening only observed frames is NOT equivalent to starting broad;
unobserved-family risks affect planning. Exact registered source execution is
54/54 in every stratum and remains the strongest cheap control. No universal NDU
advantage or risk bound is claimed. Forced consistency checking is an explicit
control, not an alleged learned strategy or a hidden free audit.

## Reproduction and audit

    python fbsde_study.py --profile effect_family_revision_v1 --output /new/effects
    python fbsde_effect_artifact_checks.py -v /new/effects

The source/world auditor imports neither runtime effect model nor planner. It
uses independent regex source semantics, forward candidate permutations and
conditional full-world enumeration; checks revised identities, ALL past receipts,
remaining checks, outputs, original byte streams and CPU sums. Mutation tests
refresh file hashes before trying to fake evidence, budgets and certification.
No hash grants execution authority. All rejected/abstained cases stay in the
score denominators. The first entrypoint wiring mistake failed before creating
a study; its log is retained. Later capacity and audit hardening does not alter
the fixed task, prior, objective or first-run answers. Final-source execution and
head/merge CI qualify separately; no full-repository/native pass is claimed.
