# Controller ledger fault fixture, stage 1

Status: INTENT_NOT_EXECUTED. This is a new pure-stdlib operational fixture;
#6253 and its source 994def0b188c5105d0ceb9ace281af7f4bd0e3b2 remain unchanged.
The identity is hcsn-controller-ledger-fault-fixture-20261112-c06d-stage1.
No Torch, NumPy, SciPy, model, ODE, adjoint or optimizer execution is authorized.

## Exact code under test and injected context

The target is the original 994def controller at
qualification/hcsn_adjoint_adam_resume/native_probe.py, SHA256
f2e0b5bf8c4c15bbfd2df967749d949acffe22e4093320aa17c7ff9fbdc84ae2.
The fixture parses that file without importing it. It lifts exactly the original
write, require and actor function ASTs and the final unknown/exact_calls
assignments. It records each selected AST hash without location attributes.
Only the aggregate function wrapper is new. No original function body or
aggregation expression is rewritten.

This is not execution of the complete original numerical controller. The lifted
functions receive a separate global namespace in place of their original main
closure. The injected args, source, before, actors, totals and checks are fixture
objects. The expected continuous-mode tuple is explicitly (0,0,0), so every real
toy reports its true zero numerical calls. No synthetic numerical call or update
is inserted into an actual denominator. The STARTING-without-PID seed separately
uses a labeled reserved bound (3,3,2); it is metadata, never actual work.

The original actor still constructs its numerical module command. A strict
adapter checks that exact executable/-B/-m/module prefix, records the intended
argv and substitutes a fresh stdlib-only toy module. The original numerical
argv is never passed to subprocess.Popen. The toy binds the new fixture source
and original selected AST identity, not an assertion that the original thirteen
numerical sources were executed. Module guards reject loaded Torch/NumPy/SciPy.

## Predeclared scenarios

There are thirteen fresh controller workers and at most ten successfully
executed toy processes. One additional real Popen attempts a guaranteed absent
executable; a failed exec may briefly fork an OS child, but no toy/actor body
executes. All controllers and toys use this one source/identity.

| Scenario | Actual effect | Required ledger outcome |
| --- | --- | --- |
| known_zero | Toy exits 0 with bound zero report | KNOWN, exact zero |
| no_child | Real exec fails with OSError | Terminal START_FAILED_NO_CHILD, known zero numerical work |
| missing_result | Toy exits 0 without RESULT | UNKNOWN, exact total null |
| malformed_result | Toy writes syntactically invalid JSON | UNKNOWN, exact total null |
| unbound_result | Valid JSON, wrong nonce | UNKNOWN, exact total null |
| wrong_pid | Valid JSON, wrong PID | UNKNOWN, exact total null |
| wrong_source | Valid JSON, changed source binding | UNKNOWN, exact total null |
| wrong_exit | Valid JSON, reported exit differs | UNKNOWN, exact total null |
| noninteger_counter | Float zero instead of exact int | UNKNOWN, exact total null |
| pre_popen_kill | SIGKILL after STARTING is persisted, before real Popen | STARTING, PID unknown, UNKNOWN/null |
| post_spawn_pre_pid_kill | Actual toy spawned and reaped, then SIGKILL before returning PID | STARTING, PID unknown, UNKNOWN/null |
| post_pid_kill | Actual toy reaped, then SIGKILL before wait returns | SPAWNED/PID persisted, UNKNOWN/null |
| starting_no_pid | Seeded unresolved intent, no adapter call | UNKNOWN/null with reserved bound retained |

For every unknown case, a second admission must reject before any adapter call.
The supervisor independently rereads the last durable ACTORS file and evaluates
the lifted original aggregate expressions. It does not pretend that a dead
controller emitted a terminal report. All intentional kills are confined to the
fixture worker's own PID; authoritative supervisor wait must return -SIGKILL.

The two post-spawn kill controls deliberately reap the zero-work toy first.
They test controller ledger persistence after an exited child, not cleanup of
an active optimizer or an arbitrary orphan. Toy PID, actual argv, exit and reap
witnesses are retained before killing the controller. Empty/malformed/unbound
RESULT tests do not assert strict duplicate-key, NaN or arbitrary hostile JSON
validation. This fixture does not resolve any historical UNKNOWN numerical job.

## Bounds and failure accounting

The only planned admission is one normal PR-hosted run after source/spec/request
freeze and independent static review. No local runtime pretest is authorized.
Budget: thirteen worker processes, ten executed toy processes, one failed-exec
Popen, three deliberate self-SIGKILLs; zero numerical API calls. Each toy wait is
limited to three seconds, with targeted kill/reap on timeout. Worker waits are
eight seconds; only that admitted worker PID is killed/reaped on timeout. The
whole hosted job is limited to five minutes. A two-MiB payload check occurs
after execution; it is not an OS hard filesystem or RSS cap.

Every supervisor launch intent and observed PID/exit is persisted. An incomplete
protocol reports exact process totals as null, keeping only separately labeled
observed PIDs/completed-case toys. The planned three SIGKILL cases are
separate from the observed authoritative SIGKILL exits; unadmitted cases are
never counted as actual kills. It never labels an unreported actor as zero.
RUSAGE_CHILDREN CPU/max-RSS and wall time are measured for the fixture process
tree; reported max RSS is not simultaneous aggregate RSS. Source bytes are
checked before/after, all raw stdout/stderr/events/ACTORS/admissions are retained,
and any RED or incomplete result is preserved without replacing this identity.

## Qualification boundary

A PASS only dynamically validates these injected zero-work controller ledger
paths on the same running OS. It is not a numerical, optimizer, model, n512,
full-network, prior/migration, task-benefit or adoption qualification. It does
not prove power-loss directory durability, arbitrary malicious Python,
checkpoint attestation or active-child cleanup. Global HCSN remains HOLD.
