# Exact finite binary64 add/subtract stage (HOLD)

This isolated source stage decodes two finite binary64 inputs into exact
integer ratios, performs one addition or subtraction, and rounds the result
exactly once under roundTiesToEven through the frozen #6320 primitive.

Exact cancellation uses the IEEE round-to-nearest zero-sign rule: an exact zero
is negative only when the two effective addends are both negative. The stage
covers normal, subnormal, cancellation, underflow and overflow results and
rejects nonfinite operands. Its deterministic reference is test-only hardware
binary64; the implementation constructs no Python float and imports no
struct, fractions, NumPy, SciPy, candidate, or oracle.

Only finite binary64 single-operation addition and subtraction are covered.
FMA, multi-operation evaluation order, provider loading, authentic N256 input
execution, the packet operator, resources, and the 18,225,028-record comparison
remain OPEN. No numerical candidate, model, Torch graph, or optimizer runs.

Historical RED and UNKNOWN results are unchanged. Global status remains
HOLD / all_closed=false.
