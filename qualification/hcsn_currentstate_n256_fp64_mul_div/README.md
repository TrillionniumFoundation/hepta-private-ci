# Exact finite binary64 multiply/divide stage (HOLD)

This isolated source stage decodes two finite binary64 inputs into exact
integer ratios, performs one multiplication or division on those ratios, and
rounds the result exactly once under `roundTiesToEven` through the frozen
rational-rounding primitive from Draft #6320.

It preserves multiplication/division signed-zero XOR behavior, covers normal,
subnormal, underflow, and overflow results, and rejects nonfinite inputs and
division by either signed zero.  Its deterministic test-only reference uses
CPython hardware binary64 plus `struct`; the implementation constructs no
Python float and imports no `struct`, `fractions`, NumPy, SciPy, candidate, or
oracle.

Only finite binary64 single-operation multiplication and division are covered.
Addition, subtraction, FMA, multi-operation sequencing, provider loading,
authentic N256 inputs, the packet operator, resource qualification, and the
18,225,028-record comparison remain OPEN.  No numerical candidate, model,
Torch graph, or optimizer is executed.

Historical RED and UNKNOWN results are unchanged.  Global status remains
`HOLD / all_closed=false`.
