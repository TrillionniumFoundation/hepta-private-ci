# N256 warm-1 independent-oracle implementation gap

Status: **ORACLE_IMPLEMENTATION_REQUIRED / HOLD / all_closed=false**.

This source-only review follows Draft #6611. It identifies an implementation
gap before any authentic N256 numerical admission: the executable candidate
stores pending packets with alpha, generator, and output, while the inherited
legacy “independent oracle” packet type lacks output and its propagation and
coordinate stream do not carry pending packets. The newer v2 adapter validates
authentic input bytes only; it deliberately performs no propagation.

Therefore the legacy oracle cannot serve as the independent reference for the
69,728-coordinate warm first-step capsule. A future independently frozen oracle
must assemble its own dense operator, carry packet fragments and emissions,
preserve deterministic delay, reset, permanent upper escape, and signed
content, and emit all 2,600 state plus 67,128 packet coordinates including 264
packet-output values. For warm 0→0.001 its frozen call envelope is one dynamic
step and two dense matrix-exponential actions.

This review imports none of the inspected implementations and executes 0 N256
serialization, dynamics, matrix exponentials, Torch calls, or optimizer steps.
The first local verifier invocation is preserved in `DEVELOPMENT_RED.json`: a
direct file-path invocation could not resolve the repository-root
`qualification` package and exited before the review imported or inspected any
source. A second invocation over-constrained the AST observation to `_advance`;
the unchanged candidate reads packet output in `_template`, which `_advance`
calls. Both failures and their minimal review-only corrections are retained.
The future oracle source, reviewer, comparator, runner, admission, resource
snapshot, and unique key remain null. Historical RED/UNKNOWN, C2 full replay
0/6, HPCA NoUpdate/external custody, equal-budget benefit, full-roster and
finite-domain qualification, production adoption, and `all_closed=false` are
unchanged.
