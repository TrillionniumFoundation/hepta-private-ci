# Explicit finite binary64 sequence stage (HOLD)

This isolated source stage evaluates a nonempty, explicit register program in
declared order. Add, subtract, multiply, and divide instructions each use one
frozen single-operation binary64 rounding boundary. FMA uses one frozen fused
boundary and does not round its product first.

Inputs and every stored intermediate must be finite canonical binary64 hex.
Division by signed zero, nonfinite operands, nonfinite intermediates, unknown
registers, unsupported operations, and noncanonical instruction shapes are
rejected. The evaluator does not mutate the caller's input dictionary.

Only this bounded explicit instruction interface is covered. Arbitrary Python
evaluation, compiler contraction, Decimal conversion, provider loading,
authentic N256 inputs, packet dynamics, resources, and the 18,225,028-record
comparison remain OPEN. No model, Torch graph, optimizer, or N256 dynamic runs.

Historical RED and UNKNOWN results are unchanged. Global status remains
HOLD / all_closed=false.
