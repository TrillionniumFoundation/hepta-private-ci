# Frozen next-stage continuation compilation research

## Scope and candidate

The only new decision candidate is J_COMPILED: the exact finite-state Bellman
policy under each original checkpoint's stored own law and original decoder.
Its terminal values use the fixed deadline-six posterior and all action costs,
READ current-at-due events, sensor REPAIR, and full owner state follow the pinned
task. It receives public schedules and available histories; it never receives
the evaluator law, labels, opened future packets or realized future outcomes.

The compiler retains the complete lawful Q DAG as an auditable witness, then
emits a closed selected-policy automaton, preserving all structural observation
branches including zero-probability branches. Complete-state transitions,
terminal updates, selected actions, and initial expected utility must match
exactly. Dense versus sparse are execution ablations, not different quality
candidates or successful weight edits. The graph bound is4096 states, six
actions and three ordered edges per action. Overflow stops, without dropping
the world or resampling. Source-order f64 += recurrence and lowest-index action
ties are mandatory; Python builtin compensated sum is not substituted.

C, D, T and K are preexisting, byte-frozen references. K is the already sealed
per-fit selector output from prior causal v2. D is the previous Q-head candidate;
T is the previous full-network gradient-training candidate. Their original
information, training and selection budgets differ from this compiler; this is
a fresh common evaluation, not a matched-budget training efficiency experiment.
No new gradient training or parameter solver is authorized by this protocol.

## Feasibility DISCOVERY

Use only all320 original TRAIN worlds and144397 cached complete state inputs,
plus the previous own-law teacher arrays, before any new DEV entropy. Verify
strict original forward scores against cached C scores. For each own-law target
action, compute the maximum over legal competitor constraints of the infimum
single-constraint L2 displacement in the fixed147 Q readout coordinates. Strict
tie-priority constraints need not attain this infimum. A
terminal competitor that outranks the terminal target remains an immutable
obstruction when belief and representation are fixed. The maximum is necessary
for simultaneous satisfaction and is not generally sufficient. Include exact
ties where a lower-index immutable terminal prevents the target action.

For all4324 coordinates, use tanh/sigmoid global Lipschitz bounds with fixed
physical inputs. With rA and rB the first-layer and readout displacements,
X=||[x,1]||, H=||[h,1]||, and pair-specific M,B,
the score-gap change is at most M X rA + B H rB + B X rA rB,
which is at most L r + (B X/2) r^2 for L=sqrt((M X)^2+(B H)^2).
Here q_j=w_j^T h+b_j, and terminal scores are +/-[2 sigmoid(z_b)-1].
Tanh is1-Lipschitz and a single terminal score is0.5-Lipschitz in its belief
logit. The pair constants are:

| Score pair | M | B |
| --- | --- | --- |
| continuation j versus continuation k | norm(w_j-w_k) | sqrt(2) |
| continuation j versus terminal | norm(w_j)+0.5 norm(w_b) | sqrt(1.25) |
| continuation j versus STOP | norm(w_j) | 1 |
| opposite terminal actions | norm(w_b) | 1 |
| terminal versus STOP | 0.5 norm(w_b) | 0.5 |

The hidden shift is at most X*rA; the new augmented hidden norm is at most
H+X*rA. Cauchy-Schwarz combines the linear terms and rA*rB<=r^2/2 controls
their cross term. These bounds allow all four readout rows and all48 hidden
units to move simultaneously, so they do not rely on the prior two-unit edit.
Solve the positive quadratic root as a necessary radius. Numerical results use
f64 arithmetic, not interval arithmetic. Report weighted distributions using
full-support uniform weights, recovered original eligible-state occupancy,
occupancy times own-law action gap, and disagreement occupancy. A small lower
bound cannot establish actual reachability or global architectural feasibility.
No proposal or radius is tuned in response to these results in this experiment.

The common radius is0.5||original C_Q147||. Physical law and85->tanh48->4
architecture are fixed for the feasibility question. The compiled automaton
changes the inference program and lies outside that weight-edit constraint.

## Data independence and primary

Exclude all3456 known historical schedules by their established content hash,
including the failed/unscored40 v1 DEV,40 v2 DEV and160 v2 CONF. New DEV uses
fresh os.urandom entropy only after sources and model hashes and discovery
records are sealed:4 IID worlds per each of five fits,20 total. DEV only checks
contract/cost qualification; no model selection, hyperparameter changes or
protocol repairs follow DEV. After complete DEV results and fixed strategy are
sealed, release separate fresh CONF entropy and freeze16 IID plus16 OOD worlds
per fit,160 total. Exclude new DEV from CONF. Collisions stop without resampling.
Same original fits11,23,37,53,71 are the five independent units; world count
does not enlarge n. Content nonoverlap does not itself prove independence;
entropy is locally generated with no external custodian or preregistration.

Primary tests are J_COMPILED-C IID/OOD and J_COMPILED-K IID/OOD: four simultaneous
two-sided Bonferroni familywise95% paired Student-t intervals, df4, over five
fit-level mean utilities. A superiority gate passes only if lower>.005. The
Student-t distribution/normality approximation is explicit. These four tests
are one new family, not merged with prior experiments' tests. D/T comparisons,
belief calibration, cost and memory are descriptive. No alternate primary is
promoted after results. Each world's evaluator has its unchanged declared law
and original decoder; results remain fixed-deadline endpoint-task utility and
do not demonstrate trading returns, First-Passage or financial Call/Put value.

## Sources, execution, cost and rollback

Zero-forward preflight checks all imports/interfaces, complete historical
exclusion, cached dimensions, expected keys, original/candidate identities and
source syntax. Peer static review precedes the one freeze and single science
attempt. Numerical threads1, affinityCPU7, science hard300 CPU seconds/600 wall,
soft285 CPU seconds, RSS1GiB. Every failure and partial artifact is preserved;
no automatic technical retry. Record all original model bytes and restoration
copies, source identity before and after, stage CPU/wall and supervisor usage.
Only the new isolated research directory is writable.

Costs separate own-law graph construction, full cold preparation including
validation/serialization, dense/sparse bytes and parse times, graph/state/edge
counts and expected policy decisions. Every public schedule is unique and
full preparation is charged once to that schedule; no unobserved amortization,
future-call count or CPU-to-utility conversion is invented. NDU selection must
retain original C and stop when net value is unidentifiable or nonpositive.
Rust verification/execution uses the exact capsule contract in
CAPSULE_CONTRACT.md and is separately measured; no production deployment.
