# R14 external sensor maintenance task

## Scope and public contract

This is a synthetic finite-state task that makes a useful intervention possible.
It preserves the R13 `Cell` as the content process and adds a persistent external
sensor fault. It does not establish a need for resetting internal neural memory,
nor a benefit of an analytic core over a generic HMM with the same information.
All estimators and policies receive the same raw symbols, actions, public
durations, remaining READ budget and task prices. The execution owner retains
the latent state. STOP is available at the initial state.

The forty states are indexed `20 * regime + 2 * phase + bit`: regime zero is a
clean sensor and regime one is faulty. The twenty-state R13 phase/bit process is
unchanged, including natural absorption, Erlang recovery and content retention.
The joint generator is

\[
Q_{task}=I_2\otimes Q_{cell}+Q_{sensor}\otimes I_{20},\qquad
Q_{sensor}=\begin{pmatrix}-.12&.12\\0&0\end{pmatrix}.
\]

The initial faulty probability is .55. These two sensor parameters are declared
task constants, not estimated physical parameters. The profile `clean` sets
both to zero. Parameters can be varied explicitly for separate, declared task
profiles without giving an actor the realized latent regime.

There are eight raw observations. Clean sensors produce the original seven
symbols with total probability .99 and alarm symbol 7 with probability .01.
Faulty sensors produce alarm 7 with probability .70; their remaining .30 mass
uses the equally weighted average of the two bit-dependent emission rows at
the current phase. A faulty reading therefore does not distinguish the bit,
although its phase dependence survives. The alarm is fallible and public.

## Actions, costs and genuine recovery consequences

| Action | Physical consequence | Observation | Cost |
| --- | --- | --- | --- |
| `STOP0` / `STOP1` | End immediately | None | Zero; reward is 1 exactly when the answer matches the current bit |
| `WAIT` | Evolve the full next interval | None | `.01 * dt` |
| `READ` | Evolve the full next interval | One endpoint raw symbol | `.03 + .01 * dt`; consume one READ |
| `RESET` | Repair the external sensor, then evolve the full interval | None | `.025 + .01 * dt` |

RESET is not the original cell's natural absorption or its explicit internal
recovery restart. The repair matrix is `[[1,0],[1,0]] ⊗ I20`: it preserves the
physical phase and true content bit. The intervention occupies the entire
interval, so no simultaneous READ is allowed. Physical dynamics continue, and
the repaired sensor may fail again during that same interval. There is no
RESET reward, hidden financial bonus, content rewrite or readout of the latent
repair outcome. All task costs are public constants and are paid during actual
sampled execution. This separates task pricing from the R13 flow-only
identifiability problem.

The `unrepairable` profile replaces the repair matrix with identity while
retaining the same .025 cost. RESET then has exactly the same successor law as
WAIT and costs an additional .025, so it is strictly dominated for every belief
and legal remaining schedule. The `high_fee` profile retains effective repair
but charges 1.0. Its reset return cannot exceed zero because terminal reward is
bounded above by 1, whereas immediate STOP has value at least .5. In `clean`,
reachable beliefs remain clean and repair has no effect beyond its extra cost.

## Reachable development witness

The witness is a public READ of duration .15 returning alarm 7. It was chosen as
a development check before any confirmation cohort is used. In `repairable`,
this history has probability .395038999453 and posterior faulty probability
.988811928312. With remaining intervals (.25, .35, .45) and two available READs,
the same `ExactBeliefDP` used for R13 gives:

| Action or constraint | Expected future net utility |
| --- | ---: |
| RESET | .687016127547 |
| WAIT | .662047158589 |
| READ | .632484986689 |
| Immediate STOP | .500000000000 |
| Best policy with RESET unavailable at every future step | .500000000000 |

The strict immediate RESET margin is .024968968958. The value of having a repair
action available is .187016127547. The difference between these quantities
matters: WAIT in the unrestricted controller can still repair later. Both
controllers use the same history and full posterior; the forbidden-action
reference is not given less information.

At the same raw history and budget, `clean` chooses READ and `unrepairable` and
`high_fee` choose STOP. All three have zero available-versus-unavailable repair
value. These controls show that the useful action comes from future restored
information exceeding cost, rather than an action bonus.

## Verification and callable API

`TaskModel(cell=None, profile="repairable", fault_probability=.55,
fault_rate=.12)` exports `Q`, `E`, `R`, `prior`, `reward`, `read_cost`,
`reset_cost`, `latency_price`, `state_count=40`, `observation_count=8` and a
SHA256 `identity` over the full task model and prices. `transition(dt)` uses the
Kronecker factorization of the finite matrix exponential. A dense independent
forty-state exponential agrees to 4.44e-16; splitting .73 into .21+.52 agrees to
6.66e-16. After repair followed by .73 time units, the faulty mass is
.083872745655, matching `1-exp(-.12*.73)`. Repair preserves the phase/bit
marginal exactly.

`transition(dt, with_grad=True)` returns the transition and its three physical
derivatives. They are exact Kronecker mappings of the existing cell's Frechet
derivatives, independently checked against the full forty-state Frechet
exponential. `dQ`, `dprior`, `dE_phys`, `dE_logits` and
`parameter_jacobians()` expose inherited physical and emission derivatives.
Public reward/fee derivatives are zero. The R14 trainer decides which physical
coordinates are admitted; this task class does not pretend to identify all
three R13 physical parameters.

`posterior(history)` replays `(action, dt, token)` records with positive
durations and rejects tokens attached to WAIT or RESET. `sample_step` returns
the owner-only latent successor, public raw symbol, realized terminal reward
and actual fee. It must be called only by the execution owner; only the raw
symbol joins the actor history. Budget and deadline enforcement belong to that
owner.

Six tests pass, including an independent 8,000-path actual-execution check for
each of RESET and WAIT under one fixed READ/STOP continuation policy. The
sampled return includes all fees and agrees with `paired_q_pi` within the
predeclared six-standard-error numerical check. A separate correlation test
starts from equal sensor and bit marginals with opposite joint correlations;
the same public alarm yields substantially different bit posteriors. This
checks that the forty-state model preserves information lost by marginal-only
closure.

Reproduce the deterministic evidence and execution tests from the repository
root:

```sh
OPENBLAS_NUM_THREADS=1 python -m tools.hcsn.task_aligned_r14_20261101.task --output tools/hcsn/task_aligned_r14_20261101/evidence/task_validation.json
OPENBLAS_NUM_THREADS=1 python -m unittest tools.hcsn.task_aligned_r14_20261101.test_task -v
```

The evidence is a finite-model development validation. It is not an independent
confirmation of learned policy gain, continuum accuracy, language capacity,
pure financial FP32, production Rust ownership or a reason to activate a
production neuron replacement.
