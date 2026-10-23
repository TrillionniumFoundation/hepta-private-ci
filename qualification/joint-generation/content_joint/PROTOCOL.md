# Executable v1: native12 and independent dense paired TRAIN portfolio

The parent adopted the new draft at d1eeee13b951 on this isolated branch. This
is one NEW research build, not an extension/reset of e7de, not equal historical
R&D spend and not a formal confirmation. Prior failures remain retained. No
controller, dynamic exit, risk/weight/LR/architecture search or formal data API.
General144 remains analysis-only and has no acceptance or training slot here.

## Fixed models, objectives and identity

Exactly families S/H/A/N, seeds11/23/47, recipes independent/native: six models
per family and24 total. All use the exact same saved pre-adaptation base per
seed, full202 input, hidden32, batch64 and Adam LR.01. All encoder/head groups
really update each step. Decoder parameters are fixed and identical to original
base/actual R provenance; their moments never advance. Independent has original
six-group native Adam. Native has a separate four-group C ABI with the same
per-parameter clocks/moments, norm5 clipping, eps1e−8 and Adam equations. No old
ABI/source/result is changed. Initialization is Wt+Wi, bt+bi; native zero law is
checked against p*q conditional on equal code for every saved inner row.

Anchor is exactly the original **average** of the sum of the two modality CE
terms: −.5(log p_y+log q_y), coefficient1 for S and.2 for H/A/N. Native's two
marginals both equal s, yielding −log s_y; its gradient is the SUM of the original
two .2-weighted marginal gradients, not half of that sum. Hand checks verify this.
A subtracts expected original decoded reward; N subtracts original joint
entropic CE at rho1.5. Native uses actual R[y,c,c]. Sparse12 and expanded144-Q
metrics/requestwise original CE are checked within1e−12 at zero and final states.
The independent objective/gradients match the old equations exactly on hand data.
Native target support <=1e−300 rejects, never silently changes the anchor.

Fourteen hand checks (eleven numerical plus three flow) passed before freeze.
Both complete preflight CPU receipts and their declared hand-work ledgers are
inherited in full by every family; the one four-group compilation is reused,
not repeated. Its CPU/source/binary hash is separately identified. Four-group
actual clocks, moments and displacement match Python Adam with mixed initial
clocks, clipping and a zero-gradient step. Actual model-load/export, probability
capture, source mapping, call counts and cap checks have hand coverage.

Freeze all local executable sources, this protocol/CALLS/TRAIN-only profile,
existing input/model/R manifests, both ABI binaries and preflight receipts before
the only TRAIN build. Any implementation failure is retained. No score-based
rerun, cap adjustment, new variant, omitted seed or favorable draw is permitted.

## TRAIN source and probability evidence

Reuse saved input bytes2304 fit/768 inner,144/48 physical sources,16 rows/source.
No noisy input dataset or formal split is regenerated. The old receipt retained
the complete inner row map but only fit's unique source set. Reconstruct the
TRAIN-only physical-source metadata/order from its known TRAIN seed and source
generation equations; verify exact unique sets and every saved inner row. This
requires twelve deterministic data templates and192 physical clean metadata
images, not new model outputs. Charge that preparation, and save the reconstructed
fit/inner row map explicitly, labeled as reconstructed rather than original.

Every final/zero/checkpoint array saves p/q or s, post-tanh h, labels, source IDs,
exact Q where audited, endpoint arrays and declared greedy metadata. The fixed
checkpoint cohort contains the first128 fit and first128 inner rows: eight whole
physical sources each, with the partition stored. No row/subset is selected from
scores. Checkpoints at updates1/128/256/512 if reached save the actual pre-update
training batch probabilities/indices/labels/source IDs and gradient, together
with post-update parameters/clocks and diagnostic probabilities. The full input
artifact and hashes identify batch input bytes. Final first/last gradients,
first/final actual displacement, per-step losses/CE/utility/norm/clipping traces,
final moments/clocks and all models are exported. Missing utility for S/H is
marked NaN in NPZ, never computed as useless padding.

Three initial native and independent observations are common immutable zero-
update controls, shared in full across families. They are not extra trained
candidates. Historical strong selected pure-CE S receives three common full
observations with KEEP/log2, all charged. Strong old H/A and repaired evidence,
their complete historical costs and any unavailable parent N reference are
explicitly retained as historical benchmarks, not free fallback candidates.

## Exact slot, observation, service and alias counts

`CALLS.json` fixes all24 training slots and36 actual service calls, their family/
recipe/seed/order and sampler seed. Recipe order reverses by model seed; family
order rotates by slot. All families receive the same six slots and allocation.
There is no candidate selection or discard after scores. Fixed per-slot RNG
seed=10000+model seed gives matched batch prefixes; useful update counts may differ.

Common: six initial forwards of768 inner rows (three native, three independent),
plus three historical S forwards. Final: six forwards of768 rows PER family.
Independent observations score KEEP and the fixed log2 pushforward Q; native
scores its one actual joint law and independently audits expanded Q at zero/final.
Intermediate observations occur only at the fixed reached updates above,256
rows each, charged to that slot. They do not alter the stopping/training policy.

Each family serves independent KEEP/log2 and native once per seed:9 calls ×64
requests=576 actual new requests;36 calls/2304 across four families. Native's
KEEP/log2-identity names alias its one actual call, adding ZERO calls or charges.
The inherited base's old64 calibration requests and nine hand-only flow PNGs
remain distinct provenance/costs, not additional new service-test requests.
The cohort is64 fixed np.linspace indices of all768 inner rows. No redraw or
cohort change if repairs are zero. Service draws native once or the original
independent two codes then fixed reconciliation; one final RGB decode/PNG only.

Each receipt saves the probabilities from THAT real forward, original pair
where it exists, action/final pair, sampler seed, source IDs/labels and every
caption/PNG/hash. Native has no fabricated original independent pair/action.
Greedy is native argmax(s) or original independent head argmax followed by the
same declared repair; neither is repaired-Q MAP. All case metrics include both-
wrong, wrong-agreement, both one-correct cases, per-head/joint/greedy and pixel MSE.

## Complete cumulative budgets and tail admission

Every family has ONE10-process-CPU-second AND12B-operator-unit ledger for its
whole portfolio. Fully inherit original base preparation3,486,924,537 units and
2.075925876 CPU seconds, including original six-group compilation. Fully add
both numerical/flow preflight work/CPU (including the one new four-group compile),
new interpreter/import/source/input checks, source provenance, all initial/
historical observations, compilation/initialization/binding/exports and common
setup. Input/library hardlinks avoid execution duplication without crediting
away provenance cost. Architecture-specific compilation and per-slot initialization
CPU are separately reported; only this mixed portfolio contains both costs.
A future independent-only deployed system would not pay unused native setup.

After actual common cost, reserve2 CPU seconds AND500M units for all nontraining
tail work; allocate the remaining allowance equally to six slots. Slot CPU and
units include its updates, norm trace and fixed checkpoints. Per-update admission
covers complete real objective/backward/Adam/evidence work. A due checkpoint
additionally requires25.6M unconsumed units and.10 CPU seconds of slot allowance;
otherwise stop the slot before that update. Other updates retain.01 seconds.
Unexecuted envelopes are never consumed padding. Check actual checkpoint units
against its envelope. No zero-useful-update model is accepted.

All setup/export/observations, final sparse/full-Q parity, real service, family
rotation/scheduler overhead and final model evidence count in the family. Final
observation admits100M/model; service admits the unchanged two-full-equivalent
reference cap,2×19236 units/request, including the actual input scan. Timers
start before per-call guard/setup and end after outputs/complete law/source
receipt export. The tiny outer timing descriptor is separately billed with
other final administration. Actual service overhead is not inferred from e7de.

The outer launcher reports child/launcher CPU and charges final lossless result/
receipt/summary administration not inside the child timestamp to every family,
without changing the original build receipt. Any actual cap violation fails and
retains everything. Old e7de ledgers remain unchanged; no total historical-spend
equality, best-static-all-budget win or deployment claim follows.

## Fixed developmental contrasts, no confirmation

Report native-minus-independent KEEP/log2 for every S/H/A/N seed. The primary
coupling check requires positive mean original CE AND joint success for S and H
against their own log2 slots. Also report native final-minus-native-zero, so
conditioning at initialization cannot be relabeled as learned improvement.
Native A−H and native N−A are the other two fixed hypotheses: each requires
positive mean CE AND joint success. Native A−S is an explicit strong pure-CE
comparison, not a substitute gate. Preserve all negative seeds/cases. The frozen
saved-output report uses exactly these contrasts, no search or new scores.

All comparisons condition on this same six-model portfolio, not a competing
system spending its entire budget on its best static architecture. Inner rows
are already used research data. No intervals here constitute formal evidence,
alpha consumption or reversal of CORE/r2. Any later confirmation requires the
parent's full history, independent sources, opening marker and honest repeated-
confirmation error control. No such data or marker is opened by this program.
