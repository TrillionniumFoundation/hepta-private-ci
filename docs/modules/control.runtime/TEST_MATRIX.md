# control.runtime test matrix

The exact machine-readable matrix is generated for each workflow candidate by `scripts/generate_control_runtime_status.py`. This document defines the required coverage.

| Area | Required evidence |
|---|---|
| Exact source | clean checkout, candidate SHA/tree receipt, source-head lane |
| Integration safety | deterministic synthetic merge against the target base |
| Build quality | `cargo fmt --check`, locked all-target check, strict Clippy |
| Planner | bounded inputs, digest binding, NDU coverage, finalization and grant-request tests |
| Planner journal | typed append, semantic reopen, selection-before-decision rejection, revoke/reselect rejection, corruption and truncation |
| Durable store | partial-tail recovery, complete-frame corruption rejection, writer exclusivity, backup and restore |
| Exact attempt | Decision → AuthorityRequested → IndependentlyAuthorized → Dispatched → terminal/reconciliation replay |
| Trusted time | future evidence, expiry during verification, grant expiry at final use, monotonic-clock rollback |
| Producer admission | owner/generation/policy/payload binding and verifier digest binding |
| Lifecycle | dependency/topology/source/policy/witness binding and final-use expiry |
| OrganHost | graph-before-index validation, unsupported profile rejection, panic containment, partial delivery, output and aggregate budgets |
| Restart | request/authorization/dispatch/`Indeterminate` recovery without automatic resend |
| Generation fence | initialization, same-generation restart, strict successor, stale restore, missing/mismatched external anchor |
| NDU regression | named-host receipt plus planner-context and intelligence integration suites |

## External evidence lanes

The following are mandatory before activation but cannot be produced by source unit tests:

- HIL qualification with the approved adapter and device profile;
- physical success, failure, timeout, late-result, restart, and reconciliation evidence;
- independent security acceptance;
- activation approval;
- release approval.

A missing external lane remains `not-established`; it is never inferred from passing source CI.
