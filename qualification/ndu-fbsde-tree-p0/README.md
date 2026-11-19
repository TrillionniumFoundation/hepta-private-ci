# NDU short-horizon FBSDE TREE shadow contract

This package is the next research-only increment after the shared Stem/Cell
artifact contracts in PR 2672 and the receipt/Reader bridge in PR 2675. It gives the
TREE/GRAPH idea a bounded, testable boundary without pretending that a forward
encoder rollout is a solved FBSDE.

## Mathematical boundary

For a short grid, the value field is the backward composition:
u_N = g, u_i = T_i u_(i+1), and u_0 = T_0 ... T_(N-1) g.

The tree may propagate bounded forward state (X,H,P,B) and carry local
continuation intervals. A sampled branch terminal value is not the global
conditional solution. The gate therefore requires terminal, interface, Z Sigma=B,
semigroup, and held-out-path evidence, plus a separated interval certificate.
Interval aggregation is explicit; branch equality is never inferred from one
rollout.

## Contract contents

- TreeNodeV1: frozen Stem/objective/prompt identities and bounded Cell boundary
  state; raw prompt text and solver/objective fields cannot cross the boundary.
- TreeEdgeV1: one positive-duration local step with Z and interface residuals.
- TreePlanV1: acyclic depth-indexed propagation, one root, exact parent links,
  shared generation identities, and a hard node cap.
- FbsdeShadowGateV1: fail-closed residual, conditioning, held-out, resource,
  and prompt-boundary checks. Its only positive outcome is ADVISORY_ACCEPT
  with DENY_ALL authority.
- aggregate_branch_intervals: keeps conditional branch uncertainty rather than
  replacing it with a sampled scalar.

## Explicit non-claims

This package does not call a checkpoint, learn a multimodal Stem, train an
FBSDE coefficient, prove global existence, decode language, or activate System2
in production. A real gate still needs independent data, a matched
deterministic/Bellman baseline, frozen weights, covariance support, and resource
receipts. The existing codex-rs/hepta-ndu recursive utility remains a
deterministic scalar baseline; it is not silently reclassified as an FBSDE solver.

## Suggested pilot

Start with depth 2--4, branching 2--8, scalar/vector U dimension <=8, driver
dimension <=32, d_h <= 256, d_z <= 512, explicit eigenvalue and condition-number
checks, and a node budget before any model invocation.
