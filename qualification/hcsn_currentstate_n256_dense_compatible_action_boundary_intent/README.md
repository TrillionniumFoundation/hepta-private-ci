# N256 dense-compatible pre-exponential boundary intent

**Status: SOURCE_ONLY / HOLD / numerical execution disabled / not qualified.**

Draft #6823 remains strict RED: its one N256 warm step and two sparse
`expm_multiply` actions produced 1,291 bitwise mismatches among 69,728 final
FP64 coordinates. Draft #6824 preserves the exact originals. Draft #6828 only
froze a high-level alternative; it did not recover or compare either action's
pre-exponential arrays.

This independent source stage defines the missing boundary without executing
it. For the fixed N256 warm lane, the boundary is exactly:

- extended generator: `257 * 257 = 66,049` FP64 values;
- initial state: `5 * 257 = 1,285` FP64 values;
- selectors: `257 * 1 + 257 * 2 = 771` FP64 values;
- total denominator: **68,105** FP64 values.

A future, separately admitted builder must publish both the independent dense
boundary and the candidate-derived boundary. Coordinate identities and bytes
must match for all 68,105 values before any exponential action is allowed. One
mismatch is RED with zero exponential calls. Only a boundary-exact later
identity may execute the two dense actions and apply the unchanged 69,728-value
final bitwise gate.

The future dense action body in `action_boundary.py` is AST-identical to the
frozen independent oracle `_stream_action`. It is not imported or called by
this stage. There is no workflow, runner, admission, input read, numerical
module import, dynamic step, exponential action, serializer call, Torch call,
optimizer step, or new idempotency key.

Passing a future dense-compatible action would only localize the old sparse
RED; it would not qualify sparse `expm_multiply`, N512, later cycles, arbitrary
histories, finite-domain accuracy, full prior, migration, full-network
AD/training, task benefit, asynchronous cost, C2 full replay, HPCA external
custody, production, or adoption. All historical RED/OOM/cancelled/UNKNOWN
records remain unchanged; `all_closed=false`.
