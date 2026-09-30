# intelligence.control adversarial audit — 2026-10-01

## Scope and source identity

The reviewed baseline is `0f0d40527db1090b8ec3ee51acbc2412a4f99c4a`, the
actual head of PR #1219 when this audit began, rather than its stale body or
`main@a126987b84737dbc2ee2592442a314117bddb4a2`. Changes are developed on
`codex/intelligence-control-adversarial-audit-20261001`. Prior logs and source
delivery capsules do not establish execution of this candidate.

The audit covers the canonical seven-owner composition, mutable-object and
digest boundaries, time budgets, Agentd worker supervision, durable learning
and native terminal recovery, and the module's qualification record admission.
It combines independent source reviews and adversarial regressions. This is a
bounded audit, not a proof that every possible defect or optimization is absent.

## Technical documentation assessment

Detailed technical development documentation exists. The stable entrypoint is
[TECHNICAL.md](TECHNICAL.md); [PRODUCT_CLOSURE.md](PRODUCT_CLOSURE.md) specifies
the actual product composition. Recovery is covered by
[RESTART_RECONCILIATION.md](RESTART_RECONCILIATION.md) and
[ADR-001-DURABLE-OPERATION-RECOVERY.md](ADR-001-DURABLE-OPERATION-RECOVERY.md).
[OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) and
[COMPATIBILITY.md](COMPATIBILITY.md) cover operations and compatibility.
`IMPLEMENTATION_MAP.json` and `TEST_TRACEABILITY.json` bind source and tests.

The baseline contains six dedicated Markdown guides, but several claims had
drifted: the runner/provider profile was described as production composition,
already optimized manifest/index lookups were described as future work, and
recovery documentation omitted the learning I/O process watchdog. These are
corrected without upgrading qualification, activation or release claims.

The PR body's `ACTIVE_PRODUCT_CONTRACT.md` and `REQUIREMENT_TEST_MAP.json` are
not baseline files. The current files above are authoritative navigation.
The audited source-delivery capsule has SHA-256
`bb0858c91872e4406b2e383c6a6ac362df853b76fb03dc96580bb8f1d0c9e244`.
The old delivery artifacts remain in Git history and on the original branch.
This candidate retires source-writing materializer jobs and bootstrap files;
qualification workflows have read-only repository permissions and inspect the
ordinary source directly. This avoids qualifying a checkout and subsequently
rewriting its source identity.

Some newer qualification helpers existed only inside a source-delivery capsule;
they are reviewed as proposed source, not counted as already implemented.

## Position and completion assessment

| Boundary | Source assessment | Completion evidence still required |
|---|---|---|
| Seven-owner cognition | Canonical, bounded, ephemeral composition exists | Candidate native test execution and owner conformance |
| Authority/currentness | Signed per-fence snapshots and independent rollback witness exist | Independent key provisioning and target-host review |
| Product composition | Atomic four-owner embedding profile exists | An authorized embedding, real provider execution and exact-head receipts |
| Physical dispatch | Existing Agentd/App Server lifecycle owns effects | Lost-ack, restart and terminal reconciliation product evidence |
| Learning persistence | Existing operation/ledger owners retain intent and facts | Crash-cut and successor-generation qualification |
| Operations | Worker capacity, watchdog and telemetry exist | Target-host resource/termination measurements and operational acceptance |
| Activation/release | External authority is intentionally separate | Independent acceptance, canary, promotion and release |

The ordinary CLI does not provide the authorized seven-owner invocation,
physical execution and learning evidence objects. Source composition is
substantial, but default-product composition and production qualification are
not established. A numerical completion percentage would mix incompatible
states and hide those gates.

The module should remain a composition facade. Improvements belong at its
validation and sequencing boundaries; durable facts remain with
`kernel.operations`, `learning.ledger`, `runtime.agentd` and the existing
physical execution owner. Creating a second store or a parallel provider path
would weaken these guarantees.

## Confirmed defects and remediation

| Finding | Failure scenario | Remediation boundary |
|---|---|---|
| Facade budget depends on adapter cooperation | A valid owner adapter ignores its budget and returns an overdue result | Measure stage and total monotonic time inside canonical composition |
| Standalone context accepts a stale decision digest | Public decision fields are changed while retaining a nonzero prior digest | Recompute the canonical decision digest before context assembly |
| Timeout/completion state is not linearized | Watchdog and request use separate counted flags; completion races publication | One shared worker state orders timeout accounting and completion |
| Provider factory can publish a late successful result | Watchdog expires while host invocation factory returns success | Check worker rejection and deadline before accepting the result |
| Native recovered terminal is not projected into Agentd | Native journal supplies a real terminal but Agentd remains indeterminate | Reconcile the same run's terminal without repeating provider effects |
| Test record trusts self-reported success | Empty/failed logs are accompanied by fabricated positive counts | Recompute counts and bind record metadata to the actual checkout/invocation |
| Readiness helper is absent and proposed helper fails open | Existing workflow names a missing script; proposed `all([])` accepts an empty object | Materialize a reviewed strict readiness verifier and negative tests |
| Registry delivery can substitute owner lineage after rehashing | Public payload, exercise or compatible snapshot fields are replaced with internally consistent hashes | Compare the DTO to private admitted owner lineage and immutable serialization bytes |
| Prompt delivery fabricates full-payload token accounting | Registered fragment token costs are reused as the token count of an arbitrary serialized payload | Require the model-profile-bound exact tokenizer for the complete serialized bytes; legacy APIs without one reject |
| Documentation and test navigation drift | Technical claims and mapped test names no longer match source | Correct the guides and validate exact source/test mappings |

The latest baseline already has final currentness fences for abstention and
slow-path terminal outcomes. An early reading of the older checkout suggested
otherwise; this was withdrawn after checking the immutable baseline. Regression
coverage is added without claiming a new source fix for that boundary.

## Verification and remaining gates

Execution results for the final candidate are recorded below after the changes
are assembled. Source references, added tests and successful declaration checks
are not substitutes for compiled native test execution. No historical receipt,
bootstrap artifact or self-reported counter grants production readiness.

Recovery also requires the host factory to reproduce the original owner evidence
and exact prepared envelope. The facade has no durable prepared-object archive;
changed context/envelope lineage is rejected rather than applied to a historical
provider result. This audit does not claim automatic recovery of arbitrary owner
evidence drift or cross-generation adoption.

The registry staging adapter extracts developer fragments from a binary source
envelope. Its tokenizer receipt covers that source envelope; the host must count
its final provider serialization separately. A source-envelope count is not a
physical request count. Concrete model-specific tokenizer implementations and
authorized live factories remain embedding responsibilities.

Seven-owner freshness and provider final-use authority are separate boundaries.
Deployment must prove that owner revocation after Decision acknowledgement and
before model send is rejected by the composed final-use issuer; a current
provider grant alone is not proof of current seven-owner inputs.

The audit cannot create independent operator acceptance, live owner credentials,
provider observations or target-host measurements. Those remain explicit gates
in the module's implementation map and operations runbook. Further optimization
should be driven by those measurements, including manifest verification cost,
worker saturation, learning recovery age and cancellation-to-stop latency.
