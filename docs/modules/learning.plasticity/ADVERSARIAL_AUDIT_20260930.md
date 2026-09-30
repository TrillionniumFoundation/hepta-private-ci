# learning.plasticity adversarial audit — 2026-09-30

## Result and implementation boundary

The module has detailed technical development documentation: `TECHNICAL.md`,
`OPERATIONS.md`, `CURRENT_IMPLEMENTATION.md`, `IMPLEMENTATION_MAP.json` and
`CURRENT_STATE.json`. The deterministic proposal engine, authenticated product
adapters, durable proposal registries, Agentd lifetime owner and external runtime
topology executor are substantial source implementations. They do not constitute
an autonomous production learning loop or deployment acceptance.

This audit starts from main commit
`a126987b84737dbc2ee2592442a314117bddb4a2` and changes the implemented safety,
recovery, resource and integration boundaries. Separate reviewers examined the
proposal engine, registries/canary, host composition and documents; a further
review traced the changed handoff semantics through the actual runtime consumer.
The final source review found no additional confirmed defect in the reviewed
changes. The product and target-host gaps below remain explicit.

## Confirmed problems and remediation

| Problem | Previous behavior | Implemented correction |
| --- | --- | --- |
| Inverted authorization bounds | Public policy authorization could accept a lower bound greater than the upper bound if both escaped neither policy endpoint. | Reject inverted request bounds; retain complete public policy authentication. |
| Repeated policy verification | Every signal cloned, sorted and hashed the complete policy after the generator had already verified it. | Borrow one immutable verified policy and perform bounded rule lookups. The public API still verifies independently. |
| Clone before resource checks | Public proposal verification copied oversized candidate/layer/change vectors before rejecting their capacities. | Check counts before cloning; avoid the flattened topology change copy; bound affected product, durable and runtime handoff inputs. |
| Producer-controlled validation time | The daemon queued the submitted `now`, allowing old timestamps or queue delays to change evidence validity checks. | The runtime samples its own Unix-millisecond clock after dequeue. Compatibility time arguments cannot select that clock. |
| Expiry during preparation | One initial time snapshot could remain valid after expensive preparation had consumed a validity window. | Sample the host clock again before append; recheck authenticated evidence context, principal validity, scheduled revocation and owner receipt windows. Rejection precedes writer state changes and durable effects. |
| Anchor initialization cursor | An empty file supplied with a nonzero cursor could receive a journal header at the wrong offset. | Seek to the start before initial header writes. |
| Indeterminate anchor writes and fence replay | A failed append could leave a reusable in-memory journal; replay accepted an unacknowledged generation skip forbidden by live issuance. | Poison the journal on append I/O uncertainty, require reopen/reconciliation, and enforce the same pending-generation rule during replay. |
| Partial enrollment header | A crash during the first header write could strand a pending generation. | Only explicit unacknowledged-bootstrap resume may complete an exact expected header prefix. Normal and anchored reopen still reject it; mismatches leave bytes untouched. |
| Topology reopen durability | Reopen could expose a complete unacknowledged suffix without the parameter registry's synchronization barrier. | Synchronize the topology registry before exposing a healthy reopened handle. |
| Same-module alternatives | Governance consumed handoffs by module alone; canary and runtime could select another alternative's plan. | Canonicalize and resolve by `(module_id, plan_digest)` through admission, signing, canary, runtime apply and recovery. Shared exact plans remain supported. |
| Canary evidence replay and budget reset | A plan omitted registry scope/fence; cumulative regression observations could decrease. | Canary plan V3 binds registry scope and writer generation; regression counts are cumulative and nondecreasing, and rejected observations do not advance state. |
| Full-history append copies | Preflight copied the entire retained registry on each append. | Reuse read-only conflict/capacity preflight under the exclusive mutable owner, then insert only the new record after durable synchronization. Unexpected postappend errors remain poisoned. |

The unchanged valid parameter/proposal/handoff digest formats remain compatible.
The canary plan digest deliberately uses a V3 domain because its scope/fence
binding changes the signed meaning. Existing Observer attestations over an older
plan must be obtained again for the new exact plan.

## Documentation source identity correction

The final strict document check also exposed seven pre-existing navigation maps
whose source anchors existed but belonged to pre-merge branches, rather than the
main candidate's ancestry: `learning.ledger`, `learning.artifacts`,
`objective.compiler`, `utility.ndu`, `cognitive.read`, `automation.taskflow` and
`control.engineering`. Retrieving complete history did not resolve this mismatch.
Their original commit/tree and observation records are retained verbatim under
`priorNavigationAnchors` as historical descriptions. Current navigation and blob
manifests were explicitly rebound to the reviewed committed source. Existing
claim boundaries were asserted unchanged, including all five false production,
execution, independent acceptance, activation and release claims. The strict
identity verifier was not weakened. The five normally anchored affected maps
were updated through the repository's ordinary migration command. In the control
map, the active navigation anchor is explicitly distinguished from the retained
historical integration baseline and external CI execution authority. The new public
guarded admission entrypoints and regression references were also mapped.

## Module completion by responsibility

| Responsibility | Current assessment |
| --- | --- |
| Bounded parameter/topology proposal generation and no-change record | Implemented source, with deterministic and adversarial regression coverage. |
| Independent Generator/Observer/Evaluator admission | Implemented product composition; signatures authenticate evidence, not the scientific truth of an update. |
| Owner evidence and numeric-value binding | Implemented within the generation's retained owner handles; no automatic external owner refresh or revocation subscription. |
| Proposal persistence, anchor/fence recovery and retry | Implemented source and local failure/reopen tests; independent physical rollback domains require deployment evidence. |
| Agentd lifetime queue and guarded admission | Implemented source with bounded queue and host-owned validation clocks; complete Agentd/process qualification is a separate check. |
| Real upstream self-iteration coordinator | Still not product-composed. The named producer is a bounded submission boundary, not a deployed autonomous trigger. |
| Live topology application and fault recovery | External runtime owner source with exact FinalUse/migration binding and regression tests; target-host execution remains unproved. |
| Longitudinal learning efficacy, telemetry, operator acceptance, activation and release | Not established by this source audit. Existing false readiness/activation/release claims remain false. |

An upstream coordinator must consume a genuinely frozen, independently evaluated
request. A safe composition needs independent binding of the iteration envelope,
base source, objective, mutation grammar, budgets and exact submitted request.
Adding another forwarding facade without that binding would not close the gap.

## Validation evidence

| Check | Result and scope |
| --- | --- |
| Actual-source proposal crate, through `just test` in a focused workspace | 68 passed, 0 skipped. Includes golden compatibility, maximum signal generation, exact alternatives, scope/fence isolation, cumulative regressions, partial headers and byte-preserving rejection/retry tests. |
| Actual-source intelligence, ledger and runtime, through `just test` in a 25-component dependency workspace | 216 passed; 1 existing target-host writer-growth test remained ignored by its original attribute. Includes the non-first exact handoff's live apply, stopped-host fault and separately authorized recovery. |
| Actual-source anchor journal, through `just test` in an isolated validation crate | 7 passed, 0 skipped. Real read-only descriptors exercise write failure, poisoning and reopen. This does not claim an injected hardware `sync_data` failure. |
| Proposal crate scoped `just fix` / Clippy | Passed in the focused workspace. |
| Repository `just fmt` | Completed; unrelated pre-existing Python formatting churn was reverted. |
| Documentation self-test, derived projection and module registry | Passed. Contract/domain lists and relative document links were independently checked. |
| Complete development-document verifier and implementation-map adversarial tests | `PASS_HEPTA_DEVELOPMENT_DOCS_V8`; 86 map tests passed. Verification includes all 40 module source bindings and retains 54 documented readiness gaps. |
| Full original-workspace Agentd/process checks | Not completed. The final scoped `just test` attempt exited 101 during dependency compilation (`starlark` / `codex-network-proxy`: `No space left on device`), before Agentd/process tests ran. Earlier attempts also encountered execution-service disconnection. The focused passes do not substitute for Agentd/process qualification. |

The focused workspaces reference the actual repository sources, retain relevant
dependency features and use the original lockfile where needed. They neither
replace the implemented components with stubs nor grant production readiness.
The newly added Agentd clock regressions in `plasticity_runtime_clock_tests.rs` have not run in the complete Agentd workspace. Their source covers queued
expiry, caller timestamp substitution, final-append expiry, clock failure and
clock regression, with full registry/anchor byte comparisons on rejection.

## Remaining gates

1. Compose the upstream frozen-request coordinator and explicit generation
   reconstruction on external owner/trust/objective changes.
2. Obtain exact source and merge-candidate Agentd/process qualification, including
   the final-clock regressions and the independent live topology canary.
3. Provision and attest genuinely independent trust and rollback domains, execute
   target-host crash/recovery exercises, and retain production telemetry.
4. Establish independent semantic/security acceptance and future-window learning
   efficacy before selection, promotion, activation or release.

These are explicit completion gates, not source capabilities manufactured by
this audit. See `CURRENT_IMPLEMENTATION.md` and `OPERATIONS.md` for the maintained
implementation boundary and operational recovery procedure.
