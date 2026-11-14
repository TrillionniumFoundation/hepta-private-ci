# Exact finite binary64 FMA stage (HOLD)

This isolated source stage decodes three finite binary64 inputs into exact
integer ratios, computes the exact product plus addend, and rounds the result
once under roundTiesToEven through the frozen #6320 primitive.

No intermediate product is rounded. Exact zero is negative only when both the
effective product and addend are negative. The stage covers normal, subnormal,
cancellation, underflow and overflow results and rejects nonfinite operands.
Its deterministic reference uses test-only standard-library Fraction and
binary64 conversion; the implementation constructs no Python float and imports
no struct, fractions, NumPy, SciPy, candidate, or oracle.

Only one finite fused multiply-add is covered. General multi-operation
evaluation order, Decimal conversion, provider loading, authentic N256 input
execution, the packet operator, resources, and the 18,225,028-record comparison
remain OPEN. No numerical candidate, model, Torch graph, or optimizer runs.

Historical RED and UNKNOWN results are unchanged. Global status remains
HOLD / all_closed=false.
