# E12 local Cell message solver: no upstream whole-tree solution supplied

**2026-10-16. DRAFT / SHADOW_ONLY / DENY_ALL / NOT A PRODUCTION FBSDE.** This is
stacked on #2489 and inherits #2488 and E12 #2143. The earlier #2489
boundary audit **started from an E12 full-tree solution**. This follow-on
removes that dependency **from the producer**: it starts at internal `Y=0`,
evolves each local forward state on its own public-prefix message, and
reconstructs backward continuation solely from registered child messages.

## Registered finite stochastic law (no new theorem)

```
phi(x) = x/(1+x*x)
X_child = X_parent + a*h*phi(Y_parent_guess) +/- sigma*s
Y_parent_mapped = ((Y_left_mapped + Y_right_mapped)/2
                   + beta*h*phi(X_parent)) / (1 + lambda*h)
Y_terminal = g*phi(X_terminal)
Z_parent = (Y_right - Y_left)/(2*s)
q = a*T*(g + beta*T) < 3/4
```

The construction is bounded and **discrete**. The entire public-prefix tree
has one shared time-indexed law and nonzero noise, with two conditional
outcomes at each node. Each local forward function consumes only `(X, Y,
coefficients)`; each local backward function consumes only `(X, two
successor continuation messages, coefficients)`; the orchestrator handles
routing and budget but never asks E12 `solve`, `operator` or `build_trace`
for a solution. This is distributed *spatial message decomposition*, not
separate OS workers, not a new neural Cell, not parallel-in-time execution,
and not a stochastic continuous-time FBSDE existence proof.

When the true unrounded global fixed-point residual is `r`, the registered
contraction gives `||Y - Y*||_inf <= r/(1-q)`. The solver returns a candidate
only at `r/(1-q) <= tolerance`. Quantized iteration uses independently coded
signed ties-to-even. The independent reviewer uses the existing E12
prefix-dictionary oracle and its own rounding, checks every iteration's
residual, count and stopping flag, recomputes the original full-tree
`X/Y/Z` martingale/terminal equations, and checks all #2488 Cell interfaces.

## Actual local source-only observations, not model evidence

Local Python 3.13 with a **compatibility reconstructed E12 test dependency**,
not the entire original GitHub E12 checkout, executed the six laws; ordinary
and `python -O` local suites both passed 38/38 related tests (including 16 new).
Single-process production and separate-review CLI both completed. These
observations do **not** replace exact-HEAD hosted checks.

| depth | coupling | synchronous Cell sweeps | forward Cell calls | backward Cell calls |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0 | 2 | 2 | 2 |
| 1 | 1/3 | 3 | 3 | 3 |
| 2 | 0 | 2 | 6 | 6 |
| 2 | 1/3 | 3 | 9 | 9 |
| 3 | 0 | 2 | 14 | 14 |
| 3 | 1/3 | 4 | 28 | 28 |

The `a=0` variant has a cheaper analytic one-map backward solution; the
second iteration above is a deliberately uncompensated candidate residual
check after 16-bit rounding, **not a demonstrated compute win**. All
`physical_*_cells` counters count Python mathematical invocations, **not**
CPU model forwards, GPU kernel dispatch, OS processes, tokens or energy.
Independent source replay, SHA shape validation and claimed timer validation
do not constitute original issuer signatures or independently attested time.

## Exact source-only reproduction

```sh
ROOT=qualification/shared-stem-system2-architecture
export PYTHONPATH="$ROOT" PYTHONDONTWRITEBYTECODE=1
python -m unittest discover -s "$ROOT" -p 'test_e12_*.py' -v
python -O -m unittest discover -s "$ROOT" -p 'test_e12_*.py' -v
mkdir -p /tmp/hepta-local-e12
python "$ROOT/e12_local_cell_study.py" produce --output /tmp/hepta-local-e12/local.json
SHA=$(sha256sum /tmp/hepta-local-e12/local.json | cut -d' ' -f1)
python "$ROOT/e12_local_cell_study.py" review \
  --candidate /tmp/hepta-local-e12/local.json --sha256 "$SHA" \
  --output /tmp/hepta-local-e12/independent.json
```

## Hard no-go boundaries

No pretrained model, original human-label task, learned coefficient, new
Encoder weights, true OS-process-per-Cell implementation, longitudinal
independent utility, multimodal generation, end-to-end equal-budget system
benefit, global Brownian well-posedness, signed original source issuer or
production owner. E13/E14 real-model negative results and archived original
Reader inadequacy remain binding. No change to NDU/Neuron owner, Q24/Q32
wires, selected bundle, Hard Objective, CAS, evidence writer, FinalUse,
blocking CI, main or promotion. Source HEAD and prospective merge Actions,
architecture and `blocking-ci` must independently pass at this exact SHA.
