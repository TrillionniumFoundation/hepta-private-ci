# Content mechanism A: frozen research definition

This additive study uses **HX stationary value-feature gating**, implemented by
[`ContentValueCell`](content_model.py) and [`stream_held_inputs`](stream_time.py).
Its parent kernel/update definition is `cells.py` at
`f355cfe2ae96b2bc9a5409f8eeb857894f1b0c5b`. It defines no task-regenerative
optimal-control problem and makes no global task/NDU optimality claim.

## State, boundary and update

For batch size N, K supplied keys and width H, retain memory h and recovery r
with shape [N*K,H]. One core and one answer head share weights across all keys;
state storage still grows with K. Fresh episodes externally set both states to
zero. WRITE, QUERY and NOISE cause no internal threshold/reset event.

HX parameters, input/memory projections, feature coefficients, recovery strength
and recovery time are learned. The bounded financial parameterization, fixed
P=1/tax=.25/recovery=.60, and local domain checks are inherited from `cells.py`.
With theta fixed during an evaluation, b0(theta) is the stationary HX boundary,
b=b0*exp(.25*tanh(Wb*u)), V=P*(2.4+2*sigmoid(Wv*u+.2*h)), and x=log(V/b).
The dual features are HX equity E/V and first-hit probability F(x,maturity).
Conditioning b on input supplies stationary features; it does not define the
first-passage law of a moving boundary along the observed input history.

Each substep recomputes rate/target from its current state and held input:
`h_next=h+(1-exp(-rate*dt))*(target-h)`. Recovery then exponentially approaches
`abs(h_next)` with its learned time constant. The rate and target are frozen
only within this substep; refinement approximates the nonlinear state dynamics.
There is no absorption density, refractory queue, same-step refiring or reset
map in A. The separate historical population mechanism B is not used here.

## Input authority, content and time

[`content_tasks.py`](content_tasks.py) defines exact one-hot WRITE, QUERY, NOISE
and SILENCE; key and payload cardinalities follow its `oracle_targets` checker.
Only x and physical duration dt enter the model. Query payloads are absent;
last-write targets, query masks and the symbolic checker remain supervision.
The answer head has values+1 classes, including a never-written-key answer.

The identity encoder and exact symbolic key router are shared experimental
priors, not learned semantic addressing or a pretrained multimodal frontend.
WRITE reaches its addressed state; other keys see silence. NOISE payload is
visible to all key cores with its explicit noise tag. QUERY's key selects the
answer state; changing that key does not change routed core inputs. A query
interval can still evolve h/r: read access is not a state-freezing operation.

An event becomes visible at interval start, is held through that interval, and
its answer is read at interval end. Typed content episodes require positive
physical durations; a zero-duration WRITE would not be an instantaneous write
under this continuous-drive mechanism. No instantaneous event update is defined.
`seconds_per_model_time` explicitly converts seconds to model-time units.
Refinement holds original durations, inputs and observation endpoints unchanged;
it divides numerical integration steps without adding writes or information.
The current generated batches use uniform durations; irregular inputs need the
explicit stream API, never an averaged dt. Other baseline cores need separately
qualified irregular-time/state adapters before this comparison can include them.

## Objective, interventions and continuation

The objective is cross entropy on masked QUERY positions only. Every selected
target is the last authoritative WRITE for that key, or the unknown class.
No oracle dictionary is used as model state. Paired query-swap, overwrite,
silence, interference and unknown cases preserve the declared physical horizon;
base and silence are identical inputs and are not independent replicates.
This is typed synthetic multi-query recall, not general/open-vocabulary MQAR.

Stream continuation carries every key's h/r, end time and time conversion.
It must preserve batch/key ordering, parameters, head, schema and episode
identity. Same-process chunk equivalence alone does not qualify durable storage,
fresh-process loading, optimizer/RNG recovery, crash windows or ownership.
Those guarantees require their own identity-bound state artifact and evidence.

## Evidence boundary and comparison registration

Kernel gradients, task-loss gradients and endpoint refinement are distinct
checks. Finite fixtures and successive grid differences do not prove global
convergence; moving-boundary first-passage error is undefined in this profile.
No current fixture establishes trained content quality, real-media improvement,
unknown-generator generalization, model-scale benefit or a quality/cost frontier.

Margin-only, single-channel, smooth gate, CfC, SSM and attention comparisons
must separately register identical inputs/addressing, active-capacity policy,
search trials/seeds, stopping rules and full training/evaluation/failure costs.
Equal H is not equal parameter count; nonzero gradients from one batch only
bound observed activity. Removing unused channel coefficients does not establish
matched capacity or equal tuning. Shared-key state and routing costs also count.
The original `full.json`, 170 identities, 400-update budgets, failures and pinned
CUDA source remain unchanged; this content study cannot spend or replace them.
