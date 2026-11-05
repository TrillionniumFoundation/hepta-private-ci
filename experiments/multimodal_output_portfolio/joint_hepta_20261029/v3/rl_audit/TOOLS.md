# Real-tool equivalence control

This is an engineering and attribution sanity study. It does not qualify a new
algorithm, a trained language model, or a general code-repair agent. The frozen
generator is a string-repair rule. Its two known edits repair a parameterized
affine Python function with zero, one or two seeded bugs. Every CHECK and REPAIR
is an actual waited Python subprocess. A separate final ORACLE subprocess tests
25 complete outputs against independently constructed arithmetic expectations;
it does not count repair markers. Software separation is not administrator
independence. The source template and model are fully known during development.

The controller sees only an immutable sequence of its actions and public
outcomes. CHECK reports the number of failed intercept/slope behavior checks.
REPAIR hides whether a substitution occurred and reports only `attempted`.
STOP explicitly delivers; expiry, cancellation and tool failure cannot deliver.
All attempts retain their cost. Final verification runs and is charged even on
failure, expiry or cancellation. Repaired source without STOP earns no quality.
Repair does not read evaluator ground truth; it applies the two fixed rules.

## Four cells and the deliberately null training contrast

| Training row | Strong fixed schedule | Learned dynamic control |
| --- | --- | --- |
| Inherited flat entropic trajectory score | exhaustive best schedule | trained tabular softmax, greedy deployment |
| Recursive entropic reverse derivative | the same exhaustive best schedule | independently updated, identically initialized actor |

Both rows optimize the same eta-2, undiscounted complete-trajectory certainty
equivalent. Flat trajectory enumeration and conditional recursive derivatives
must agree. The flat implementation is also checked against the inherited
`joint_hepta_20261029/oracle.py` formula, and both against finite differences.
They receive the same known model, legal action set, initialization and update
count. Their actual CPU costs are reported separately; equal updates do not
mean equal compute. No sampling, unknown-model identification or approximate
critic is hidden in these updates. The actual legacy Torch learner minimizes
an unnormalized exponential moment; its population direction is proportional
to this normalized CE direction, but its finite-sample optimizer is not run.

The fixed column does not consume fitted parameters. Its training contrast is
structurally zero and cannot establish a training benefit. Equality of the
dynamic rows is expected algebraic equivalence, not successful independent
replication of a novel algorithm. A future efficacy factorial needs an actual
learned component consumed by both inference modes and a distinct, justified
training update. This experiment labels neither training row ordinary mean RL.

The fixed baseline exhaustively searches all 31 schedules ending in STOP within
five decisions. A separate exact adaptive planner shares the same finite model
and public information. It is executed through the real tools as an additional
reference. Service uses argmax policies; training uses stochastic softmax
policies. Both choices are registered and evaluated without conflating values.

## Freeze and run

`protocol()` registers three fit seeds, 500 updates per row, all tariffs, task
parameters and the execution-order rule. Development tests use other seeds and
short fits. The formal `run_study(seeds=[...])` is called by the source-bound
parent runner only after publication of its source and protocol freeze. Each
cell executes the same nine template instances. This finite repeated-template
roster is not a hidden benchmark or a future time window. All physical rows,
model arrays, state ordering, fit traces, process outputs and failures are kept.
Separate qualification controls execute syntax failure, exit-zero malformed JSON,
a timed-out running worker and cancellation after one action. All raw command
output and waited exits are retained. Tool output schemas are checked before
consumption. Original termination and verification status are distinct, so a
later verifier failure cannot erase an earlier cancellation or expiry.

## Costs and interpretation

Declared action credits are a research objective, not measured money. Whole
episode wall time encloses source creation, control, tool processes, waiting,
final verification and cleanup. Parent CPU and waited child CPU are separate
subtotals. An episode envelope must not be added to its enclosed action clocks.
Unsupported child CPU, per-episode RSS and monetary prices remain null; the
parent runner separately measures the complete study process including imports
and serialization. P95/P99 use only nine observations per cell and are descriptive.
Failed commands, timeout exit codes, cancellations and no-update fits stay visible.

One-time setup, training and qualification CPU are distinct from service CPU.
Only equal observed quality and a positive CPU saving permit a descriptive
CPU-seconds quotient. It is labeled `services_measured_scope_only`, since those
one-time subtotals omit outer provisioning/import/publication costs. The qualified
full-cost break-even count stays null. Tool credits are never divided into CPU
seconds. A nominal tariff benefit does not demonstrate physical compute savings.

Real frozen-LLM/multimodal control, learned approximate critics, rsEAC replication,
unknown-model robustness, generalization, independent evaluators, future windows
and total-cost training/inference benefit all remain open.
