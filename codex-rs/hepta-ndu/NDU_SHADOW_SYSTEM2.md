# NDU shadow System2 controller

`shadow_system2.rs` provides the first owner-local System2 boundary for a
shared Encoder group. It is deliberately a pure fixture controller: it does
not execute a model, mutate runtime state, grant authority, or claim that a
learned critic has emerged.

A caller supplies one `NduShadowRequestV1` containing the input, stem,
Encoder, group-adapter, critic, trajectory, and policy digests. The immutable
`NduShadowPolicyV1` bounds the maximum depth and per-step budget, then applies a
small deterministic rule:

- uncertainty or risk at/above a trigger requests at most one more depth step;
- the step is refused when the depth ceiling or remaining resource budget is
  exhausted;
- if the projected risk or uncertainty remains above the abstain threshold,
  the suggestion is `Abstain`; otherwise it is `Hold`;
- every result carries `request_digest`, `policy_digest`, `receipt_digest`, and
  `AuthorityPosture::DENY_ALL`.

The receipt is evidence for a later Group NDU policy gate. A future learned
critic can replace the fixture fields offline, but promotion should preserve
the same bounded request/receipt shape and replay checks. The controller keeps
System2 depth, resource use, abstention, and provenance visible at the group
boundary while leaving production runtime execution unchanged.
