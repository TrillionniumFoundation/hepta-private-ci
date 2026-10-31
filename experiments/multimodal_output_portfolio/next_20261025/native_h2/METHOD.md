# Complete H2 teacher inside the original owner

## Decision and evidence boundaries

This study preserves the evaluated seed-17 enriched 32-wide conditional-moment
teacher and the V6 generator. Native Rust computes the final five conditional
exponential moments and chooses the smallest admitted feasible value. The public
model service computes its frozen normalized first layer. H2 permits all five
actions. At H1, semantic refinement retains the same output and costs .002, so
the existing pointwise dominance mask remains in force.

The teacher estimates conditional exponential moments with gamma 2 and a nominal
.002 charge per non-stop action. Its previous fitting procedure used source
cross-fitting and conditional H1 predictions in H2 backups. These finite neural
approximations are not an exact Bellman solution, a continuous-time Merton
solution, or a global portfolio optimality certificate.

The new admission target is the correctness of the **immediate actual emitted
output after an action**. This target is kept for both horizons. It is not changed
to an unmasked teacher's eventual terminal correctness. The admission constraint
can exclude a semantic investment whose current draft is poor but whose later
output could improve. Consequently, numerical moment parity does not mean the
whole masked policy is the previously evaluated unrestricted teacher. Every
decision records the unrestricted teacher's choice, the choice on the actual
admission set, and whether admission changed that choice. The primary native
comparison uses a correctness-argmax policy with the same native admission and
resource rules. The independent control study's positive unrestricted-teacher
result does not transfer to this comparison.

The original H2 backup minimizes the cross-fitted H1 moments over the original
action set, with only its H1 semantic-dominance mask. It was fitted before the
new correctness admission head and does not back up this owner's future
admission set, resource failures or terminal rejection utility of -1. Applying
the new gate at each decision therefore does not solve the Bellman equation for
the newly constrained problem, even if the original moment head is numerically
reproduced. The present experiment evaluates that explicitly defined masked
teacher; it does not establish a constraint-aware or globally optimal portfolio.

## New correctness candidate and ABI

The first development candidate uses two 32→5 logistic heads on frozen teacher
activations, 330 new parameters. The second candidate uses two public
763→64→5 networks with fit-only normalizers, 98,442 new parameters. Only these
correctness heads are trained. The generator, teacher, public reader and separate
private audit observer remain frozen. Both development candidates use only the
historical forecast fit/selection data. The first candidate and its failure are
retained independently.

The second candidate's 103-coordinate public ABI consists of four observed
absence coordinates, two candidate-action flags, the remaining horizon, 32
teacher activations and 64 correctness activations. The public encoder executes
both first layers; its measured execution cost belongs to the request. Rust loads
and executes the five-action teacher's final layer and the corresponding
64→5 correctness final layer. Neither head receives a target, source identity,
future random state, private audit score, or hidden counterfactual outcome.

Three fixed ID bins are defined separately for each horizon and action. Their
cuts come from historical fit predictions and are fixed before new calibration.
New calibration estimates the bin rates, including the empirical public-absence
rate. The original four gates remain: pooled calibration/verification ECE at most
.03, pooled OOD false acceptance at most .004999, ID acceptance at least .25, and
the verification writer-level one-sided 95% OOD upper bound at most .004999.
Neither these point ECE gates nor pooled gates certify a population ECE bound,
each individual action, or selected-state calibration. Those additional ECE
diagnostics are reported explicitly.

## Prospective sources and stopping rule

The source allocator and allocation are frozen independently. Their three roles
are 100 new calibration writers with one pair each, 1,000 new qualification
writers with one pair each, and 64 new execution writers with two pairs each.
These writers and selected pixels do not overlap one another or the preceding
registered studies. Metadata-only verification is in `SOURCE_STATIC_AUDIT.json`.
No model outcome from these roles may be read before the respective prospective
protocol and actual candidate identities are frozen.

Old development first separates the 128 historical selection pairs into 64
pilot-calibration and 64 held verification pairs by fixed case parity. A failed
old feasibility candidate does not open the new roles. The old 64-pair OOD upper
bound is too wide to satisfy the eventual 1,000-writer gate; this is recorded,
not relabeled or relaxed. Feasibility checks use original ECE/nonvacuity limits
and zero observed old-source OOD false acceptances.

After both 64/64 pilots failed, a separate larger historical development stage
was authorized and registered before its own outcomes. It keeps the second
predictor's exact weights, cuts and three-bin rule, excludes the 128 pilot pairs
from the original forecast-calibration role, and fixes a hash-ordered 400/400
calibration/held split with 72 unused pairs. One cycling ID view and one absent
view per pair, one draw, and all 25 state/action outputs give 40,000 actual
outputs. The calibration frequencies are persisted before held generation.
No new XNIST sources belong to that historical stage. It is a new feasibility
stage, not a reversal of either pilot failure or independent qualification.
Because source and view/draw exposure also differ from the pilot, it does not
isolate sample size as the sole cause of any improvement.

If old development permits proceeding, new calibration collects all five causal
decision states and all five actual action outcomes across five fixed ID views,
the public all-input-absent view, and two future draws: 30,000 output records.
Qualification uses one cycling ID view and the absent view per writer and one
draw, yielding 50,000 records. Repeated states, views, actions and draws are not
additional independent writers. The cohort, cuts, masks, thresholds, observer and
sample size remain fixed after outcomes. A failed gate stops activation and is
retained; the 85 unused writers are not a reserve for expansion toward a pass.

## Causal H2 execution and recovery

The unmodified original `AgentdNeuronOwner`, native admission rules, dynamics,
resource ceilings, checkpoint/journal code, and `NduProjectionStore` are used.
The experiment adapter and model heads live in this directory. The former H1
experiment and its negative effectiveness/calibration findings remain unchanged.

Each native action is committed durably before any future generation RNG is
used. The actual PNG/text result is written, reopened and observed. A new durable
episode record binds a subsequent H1 request to that observed result's exact
public-state digest and native outcome digest. Wrong parent, state, episode,
horizon, duplicate request and pending-outcome cases are rejected before a native
tick. Recovery probes interrupt the native owner with a pending H2 decision and
restart it after a committed H2 result before H1. The original journal frontiers,
NDU projection and the new episode continuation must all agree.

The generator public state is initialized separately for each episode, but the
native owner is not. One owner per policy persists across the complete ordered
panel. Its checkpoint sequence, temporal state, activity, thresholds, eligibility
and selected NDU projection survive episode and writer boundaries; the two
restarts resume this state. Original admission reads active-fraction and
projection-count gates, the sequence window and measured resources. There is no
separate metabolic subsystem in the original owner adapter exercised here.

In this fixed port, the numerical native drive is always one Q24 unit followed
by 32 zeros. The moment and correctness heads read current public features; the
modulator digest binds the request and journal but is not applied numerically to
either head or a plasticity update. The actual generated result affects H1
through the public frame and encoder. Persistence of the NDU digest alone does
not demonstrate a numerical NDU-feedback benefit or a change to later writers'
predicted values. See `PERSISTENT_STREAM_ADDENDUM.md` for source and log evidence.

Online feedback uses the **existing deployable public sensor**, not the private
audit classifier. The bounded observable proxy is
`1 - invalid_caption - image_text_disagreement`. It can reward a consistently
wrong output, so it is explicitly not ground-truth utility or global NDU.
Only this proxy enters the NDU projection and following owner tick. The private
audit model is not even loaded until every native owner has closed. Ground-truth
terminal utility and each selected action's actual correctness are then scored
in a separate audit log. This prevents a truth score from reaching the second
decision in the same episode.

Task construction already holds target objects in the research host's memory.
They are excluded from the public encoder, runtime observer and native requests;
the isolation claim concerns the actual reviewed call/data flow, not a Python
security sandbox. Rust verifies the public-sensor receipt's identity, media
bytes, causal fields and bounds. It does not independently rerun the public
sensor or prove the reported proxy against a malicious model-service host.

This is a research owner/model-service execution. It is not a full `agentd`
daemon deployment, authenticated production outcome ownership, production trust
material, or recovery of the entire Python model-service host. Authority stays
`deny_all`; no research identity is promoted to production authority.

## Independent execution analysis and costs

The fixed native panel is 128 source pairs in 64 writer clusters, with an ID and
absent-input request for each policy. Policy order rotates by pair/view. The
primary comparison is terminal CE with gamma 2 and the original nominal action
charge, NDU minus same-admission correctness argmax. Raw utility, joint
correctness, each horizon's selected-action ECE, rejection and action counts, and
public request cost are also reported. Paired bootstrap uses 4,096 draws with
seed 261026909, resampling writers and retaining both pairs and every policy and
view together. Numerical value parity, native mechanism execution and statistical
effectiveness are distinct results.

Those original bootstrap endpoints are retained as **nominal writer-resampling
intervals for the fixed observed ordered streams**. Disjoint writer identities
do not turn a continuous stateful owner stream into 64 independently restarted
policy experiments. The bootstrap does not replay counterfactual histories when
it resamples writer rows; neither stream-order invariance nor population interval
coverage was established. This is particularly material for measured execution
cost and resource-dependent admission. The observed cost difference must not be
promoted to a universal causal cost effect. No new stream, source or alternative
statistical procedure was added after seeing the results.

Public request cost includes initialization, both encoders, all actual candidate
owner ticks, generation, output persistence/readback, public observation, numeric
verification and NDU feedback. It measures the entire request interval, deducting
only separately timed deliberate probes and recovery faults. Final row-log
serialization and the later private audit remain outside that request interval
and inside the complete child-process cost. A sum of the narrower inference,
generation and feedback stage timers is also retained and is not called the
complete request cost.
Whole-child peak RSS, native head allocation and owner transient peaks describe
different memory scopes and are not interchangeable. Every failed launch,
development trial, compilation and runtime is retained with its actual receipt.

## Reviewable implementation stages

1. Historical admission candidates and source/feasibility definitions.
2. Compact public encoder and native H2 episode/qualification adapter.
3. Actual-output qualification, independent owner execution and audit scripts.

These stages do not modify product sources or the frozen H1 experiment. Rust is
formatted with the repository's required `just fmt` before executable/code pins
are frozen. No CI is consulted.
