# Prospective repair design — not executed in this phase

This document specifies subsequent work. It does not change the current
weights, posterior adapter, likelihood, operation calibration, confidence floor,
owner dynamics, reference policy, analysis or source census. No candidate has
been fitted from the current qualification or 85-writer confirmation panel.

## The unresolved requirements

The dynamic policy's independent selected-operation ECE was
`0.03735423966942142`, above the registered `0.03` maximum. The reference
`fixed_late` policy's corresponding value was `0.029514636363636392`. These are
policy-specific results on the same ten source clusters, not interchangeable
qualifications of the posterior head. The selected-operation event includes the
actual later owner decision and final delivery. An acquisition followed by a
refusal has strict success zero.

There is also a known error in the current observation law. Some registered
pairs repeat the exact same source WAV on both sides. The input CNN is frozen
and deterministic, so the pair of observed labels for such a repeated file is
constrained to the diagonal. The present product of independent digit confusion
likelihoods assigns nonzero mass outside that diagonal. The existing fit also
does not establish independence for two different words spoken by the same
speaker. A policy can have numerically correct finite integration and still
use a misspecified model of the experiment.

Finally, numerical modulation has been shown to change actual recurrent state,
but the registered positive/zero/negative history experiment did not change the
next selected output. A claim that numerical NDU feedback improves decisions or
task returns remains unproved.

The formal episode structure also prevents identifying that effect: acquisition
writes zero delivery context, and emission is terminal. A later numerical
feedback study must include an actual subsequent decision after a delivered
output or a verified delivery failure. Its outcome observation must update
delivery uncertainty without being misrepresented as new information about
the hidden target.

## 1. Model unique evidence events and their joint observation law

Represent acquired evidence by its actual event identity, including the exact
waveform byte identity and its arrival time. Two references to the same event
must not become two independent likelihood factors. Preserve both references
for presentation and execution accounting, but update target belief with the
unique observed evidence event.

For the existing deterministic equal-digit/same-recording construction, the
conditional law must satisfy

\[
L((o_1,o_2)\mid(t,t),\text{same recording})=0
\quad\text{whenever }o_1\ne o_2.
\]

If a single-event confusion model is appropriate for that construction, its
supported diagonal probabilities are

\[
L((o,o)\mid(t,t),\text{same recording})=L_1(o\mid t),
\]

not the square of the single-event probability. This is a support and event
identity requirement, not a parameter chosen to improve a test score.

For distinct recordings from one speaker, collect actual paired CNN outcomes
and estimate a joint or hierarchical observation model. Retain the speaker as
a grouping variable in fitting and validation. Test calibration of the joint
observation probabilities and the actual next-state posterior, including rare
misrecognition branches. The old collection of individual utterances by itself
does not identify all same-speaker error dependencies.

The availability of an alias flag before acquisition must be specified as part
of the public information protocol. If source identity is available before the
action, every comparison receives the same identity information and cost. If
identity is only learned on arrival, the prior transition law must integrate
over that unknown identity. Filename class names must never become a hidden
label shortcut in the posterior or controller.

## 2. Calibrate the actual selected policy and route

Fit confidence for terminal success of the complete registered policy. Use
source-group-separated folds, with every view, route, repeated recording and
policy continuation from one writer/speaker confined to its fold. The current
qualification cohort can subsequently be declared old development, but it
cannot also serve as the independent qualification of its own repair.

Candidate calibration families can include route-aware monotone mappings,
operation-aware mappings, and regularized shared models with route/phase
features. Keep literal text, initial audio, initial visual evidence and actual
external acquisition explicit. Avoid letting many confidently negative
unselected code predictions conceal errors in the selected policy.

The acquisition target must include the later posterior update, confidence
mapping, actual owner admission and actual delivery. Changing the H1 confidence
mapping changes the H1 policy and therefore the target for the H2 acquisition
forecast. Recompute those targets on old fitting folds and freeze the resulting
policy/calibrator pair together; a calibration patch that changes only one
displayed probability is not a validated closed-loop repair.

Use a proper held-out probability loss for probability estimates and separately
measure selection-conditioned ECE, refusal rate, coverage, regret, realized
entropic return and actual execution cost. These quantities answer different
questions. A lower average calibration loss alone does not demonstrate a
better selected action or a better deployment policy.

## 3. Include actual owner state and future resource uncertainty when justified

Keep the current actual original-owner mask authoritative. If a future resource
law is added, collect actual execution samples under representative public
states and loads, distinguishing known recurrent state from unobserved future
machine load. Include refusal branches in the exponential expectation and
retain dependence between costs, observations and outcomes. Do not substitute
mean runtime for a random cost inside an exponential objective.

A learned value residual may consume genuine public owner summaries only if
its training target and held-out ablations support that dependence. Compare
the same frozen policy with numerical modulation enabled, zeroed and otherwise
specified before fresh-source evaluation. Record changes in drive, residual,
pure temporal state, eligibility, actual admissibility, chosen action and
private task utility separately. If state changes do not produce useful
decisions, preserve that negative result.

## 4. Acquire a new independent qualification cohort

The current 85-writer panel remains the registered confirmation panel of the
current frozen study. It must not be used to tune any of these repairs before
that study is completed. A subsequent calibration candidate needs newly
registered source groups with disjoint writer/speaker and pixel/waveform
identities, a declared population and a complete source ledger.

Determine cohort size prospectively using group-level uncertainty and expected
selection coverage estimated from old development. Repeated views, routes,
actions, policies or deterministic missing requests do not increase the number
of independent source groups. Keep both the original point gates and any new
uncertainty or per-route requirements explicit before outcomes are opened.

For missing-input safety, distinguish the deterministic structural rejection
proof from an empirical population statement. A future natural-OOD study must
actually include varied public OOD inputs and applicable targets or rejection
requirements. Repeating the same all-zero model state under many distinct
source identities does not establish that broader property.

## Completion criteria for that subsequent phase

The repaired candidate should have an auditable joint evidence model, a frozen
policy-specific confidence mapping, complete original-owner and physical-media
execution, and independent qualification under its declared scope. Its dynamic
policy must also beat a newly preregistered strong same-access reference under
the original entropic-return/cost analysis, with all refusals and failures
retained. Qualification and efficacy are separate requirements. Neither is
closed merely by implementing a new calibrator or obtaining a changed neuron
state.
