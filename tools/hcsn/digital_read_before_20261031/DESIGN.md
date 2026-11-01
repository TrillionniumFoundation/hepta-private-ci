# Digital read-before research v1

Execution baseline: PR 4509 commit 6c6f25f736df040e0d447e0242fb9819e15b3022.
Analytic reference: PR 4502 commit 74cf5f30a4e87a2666c57b3f8fba38f8d09fdfd3.
New code lives only in tools/hcsn/digital_read_before_20261031. Old results remain intact.

## Bounded new task

One binary hidden target, six decision slots, public per-slot duration, reliability,
price and read delay (one or two slots), initial read budget three. This is a new
synthetic partial-observation task using the inherited frozen FullHX packet model,
not a replication of the old two-job task. Six actions in fixed order:
STOP, WAIT, READ, REPAIR, SUBMIT_0, SUBMIT_1. STOP aborts for reward zero;
SUBMIT returns +1 if correct and -1 otherwise, known only to evaluator. WAIT,
READ and REPAIR advance one slot and incur the public latency price times duration.
READ immediately deducts one read budget and its fee, creates pending(source_tick,
due_tick), and accesses no packet before action selection. At the due boundary the
owner really opens that source packet and executes FullHX. A missing/invalid
packet retains all fees/time and sets broken=true; REPAIR clears broken and charges
a public repair fee. All requests must complete by the deadline; no duplicate read
while pending or broken. Deadline has only terminal
actions. STOP/SUBMIT cancel an outstanding request without refund or content access.

State: tick, budget, pending, broken, last_symbol (-1/0/+1), last_reliability,
observed history, logical elapsed time and charges. No posterior, evaluator label
or oracle Q in policy inputs. The latest completed observation is a permitted raw
input. An exact Bayes filter plus finite task DP uses the same observed information
as an explicit strong reference, never as a learned policy input.

Cell updates over the elapsed external interval use only the PRE-ACTION latest
observation: drift=bias+gain*last_symbol*(2*last_reliability-1). Newly completed
observations become inputs only at the next decision. This one-step causal update
order is shared by data, training, Python and Rust. Neuronal refractory state is
part of checkpoint; its interval-end release is explicit, at most one event per
interval. Already incurred costs remain when the next decision is STOP.

## Cell contracts and feature controls

Use 15 active representative states on (-boundary,+boundary), plus lower and upper
refractory states, common constant-drift Brownian parameters and interval clock.
ordinary: free Gaussian bins with tails folded into edge bins, no internal events.
clocked: free Gaussian endpoint outside boundaries enters respective refractory.
first_passage: killed Brownian bins plus competing first-exit boundary masses.
Refractory release probability 1-exp(-rate*dt), release into a declared reset-bin
law at tick end; fresh events do not release in the same interval. This is a finite
projected process, not exact continuous regenerative dynamics.

Physical parameters: boundary, diffusion, gain, drift_bias, reset_plus,
reset_minus, recovery_rate. Bounded transformations keep all kernels in a declared
domain. Inactive ordinary reset/recovery parameters are frozen and counted as
inactive, never used to fake matched capacity.

Features: 3 fixed relative thresholds (-.5,0,.5)*boundary and 3 horizons
(.25,.75,1.5). Nine call probabilities from the same free Brownian law; puts are
complementary outputs, not extra inputs. Add x/boundary and two refractory flags
for 12 features. Refractory rows have zero call and position features, with mode
flags; their call+put mass is explicitly active-only. Forecasts are labeled
free_endpoint_conditional_on_active; they do not pretend to include future reset.
Base feature control: powers 2..10 of x/boundary, position, two mode flags (12).
Strictly equal Gaussian/probit bank is a numerical control, not an extra arm.

Candidate families: ordinary_base, ordinary_bank, clocked_bank, first_passage_bank;
and raw_history as a mandatory learned same-information control (six observed
symbols and their six effective reliabilities, zero before actual completion).
Each family exports fixed and value controllers sharing exactly one fitted cell,
belief head and Q head. Fixed uses its OWN learned belief (threshold .8), requests
available evidence otherwise, waits for pending, repairs failure, and submits at
exhausted budget/deadline. Value uses legal argmax of six task Q outputs. No owner
posterior bypass for either classifier or controller.

## Training and inference

Common random legal behavior trajectories contain actual read receipts. Oracle
targets are exact finite-task Q under TRAIN-calibrated FullHX confusion, plus
conditional target probability. They are teacher-only. Train the full expected
supervised loss over each finite cell state, propagating its complete conditional
mass along the behavior history. This is an exact gradient for that explicitly
defined off-policy supervised objective, not a policy-gradient or DQN convergence
claim. Hard deployment samples one finite cell state with persisted RNG; neural
scores and actions depend on that realized state. Report actual-outcome calibration
separately from oracle-target fit and from task utility.

All cell families use the same public vector, 12 representation features and
same hidden width, optimizer update and sample budget; also report effective
parameter count, state/table bytes and measured preparation/training/deployment
CPU. Same update count does not imply same compute cost. Primary task utility is
terminal reward minus actual query/repair and declared time costs; hardware CPU
and persistence costs are independently measured, not replaced by event counts.

The complete future public schedule is visible to every model and the DP. The
behavior policy depends only on feasibility and its own RNG, never on the cell.
Five independent fits; common TRAIN/validation worlds within fit. Publish protocol
and source before formal training, then all candidates before generating fresh
IID/OOD worlds. Never drop seeds/failures or tune on confirmation. Preserve all
negative findings. Native table exports identify the exact new Gaussian/Brownian
kernel and weights; old CTMC qualifications do not cover them.
