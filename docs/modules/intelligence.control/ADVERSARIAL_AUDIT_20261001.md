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
Successive independent reviews continued until the inspected source boundaries
produced no new confirmed actionable findings; external qualification remains
separate from that review convergence.

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
| Native lifecycle generation is compared to process identity | The control client uses spawn generation while the canonical run uses the next Running generation; a real admitted run is rejected | Keep the wire identity at spawn and validate run receipts against checked `spawn + 1`; reject overflow |
| Completed provider message is omitted without deltas | A legal done-only response yields a successful terminal with empty captured output | Collect authoritative completed messages by item identity, with de-duplication and existing byte bounds |
| Recovered output may be projected from a partial history view | ThreadRead Summary omits earlier messages after the stream is lost | Require a Full view before recovered output projection; reject partial views without replay |
| Duplicate recovery turn IDs can substitute output | Input authentication finds the correct turn but a later ID lookup selects another turn with the same ID | Require exactly one matching nonempty turn ID before projecting any output |
| Conflicting Agentd and physical terminals can lose reconciliation state | A terminal Outcome acknowledgement masks a different physical execution status | Require matching Agentd and physical terminal phases before producing or appending Outcome evidence |
| Direct native API can mix admission and canonical run IDs | A caller bypasses the product wrapper and names a different native operation | Require identical request/run IDs before touching reservation or dispatch state |
| Test record trusts self-reported success | Empty/failed logs are accompanied by fabricated positive counts | Recompute counts and bind record metadata to the actual checkout/invocation |
| Readiness helper is absent and proposed helper fails open | Existing workflow names a missing script; proposed `all([])` accepts an empty object | Materialize a reviewed strict readiness verifier and negative tests |
| Registry delivery can substitute owner lineage after rehashing | Public payload, exercise or compatible snapshot fields are replaced with internally consistent hashes | Compare the DTO to private admitted owner lineage and immutable serialization bytes |
| Complete registry output can be grafted across compilations | Another legal compilation replaces every public delivery field while the old private exercise lineage remains | Freeze the original complete delivery-set digest and reject the cross-output graft |
| Direct prepared delivery can substitute a complete valid serialization | Two deliveries share original context/exercise but have different framing and IDs; all public serialization fields are replaced together | Freeze the original complete prepared-delivery aggregate before its first consumer |
| Prompt delivery fabricates full-payload token accounting | Registered fragment token costs are reused as the token count of an arbitrary serialized payload | Require the model-profile-bound exact tokenizer for the complete serialized bytes; legacy APIs without one reject |
| Async journal/page ownership holds mutex guards across I/O | Recovery and physical execution keep an async mutex guard alive during owner calls | Keep serialization with a single permit; use short cursor locks and cancellation-safe journal checkout |
| Documentation and test navigation drift | Technical claims and mapped test names no longer match source | Correct the guides and validate exact source/test mappings |
| Ready publication can exceed the remaining budget | Final DTO construction and integrity checks happen after the last observed deadline check | Check monotonic and durable deadlines again immediately before Ready publication |
| Module declaration collides with project qualification schema | A source-only map claims generic v3 schema but lacks its observed execution contract | Register a distinct source-declaration schema and validate it through the owner verifier without granting execution |
| Legacy qualification appends skip Prepared integrity | An explicitly enabled qualification path records public decision fields after the prepared DTO was mutated | Validate the existing private Prepared seal before either qualification append; production learning already had this gate |

The latest baseline already has final currentness fences for abstention and
slow-path terminal outcomes. An early reading of the older checkout suggested
otherwise; this was withdrawn after checking the immutable baseline. Regression
coverage is added without claiming a new source fix for that boundary.

Priority assessment: the lifecycle-generation conflict blocks the real product
path and is P0 for product completion. Budget admission, timeout publication,
prompt provenance/token accounting, recovery ordering and qualification
fail-open defects are P1 boundary correctness issues. Direct native API identity
binding and documentation/schema integration are P2 integration hardening. The
receipt-only cognition facade grants no effect authority; downstream severity
depends on an actual authorized embedding, rather than an assumed default CLI.

## Verification and remaining gates

Observed verification during this audit:

- Core cognition package: `just test -p codex-hepta-intelligence`, 104 passed,
  zero skipped, including both final private delivery aggregate seals.
- Strict core lint: a package-clean `cargo clippy --locked -p
  codex-hepta-intelligence --all-targets -- -D warnings` passed. Public v1
  by-value receipt APIs remain stable; test/benchmark fixture panic conventions
  have explicit local lint allowances.
- Audit helpers: status 19, readiness 9, fault matrix 10 and review partitions
  13 tests passed (51 total). Generic schema adapter 6 and existing provenance
  verifier 86 tests passed (92 additional tests).
- Source/test mappings, fault/review declarations and derived metadata checks
  passed. Nine Markdown documents had 89 local file/anchor links checked.
- Agentd/native host `cargo check --locked ... --all-targets` passed after
  generation, API identity and cancellation-safe journal-owner repairs.
  A completed `just fix` also compiled all three packages and their test targets,
  including the completed-message collector and Full-only recovery gate. This
  is compilation evidence, not execution of their assertions.
  The later duplicate-turn, terminal-phase, direct-delivery seal and legacy
  qualification-entry repairs require their own final compilation/execution
  result; current closing results are recorded on [draft PR #1290](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1290).
- `just fix` was run for all three modified Rust packages. Existing Agentd
  automation/cognitive/plasticity lint debt remains outside this module and
  can still block the repository's broader strict lint gate; it is not hidden
  by weakening that gate.

Earlier native test attempts ran out of shared disk while compiling dependencies.
Another local retry was terminated by SIGKILL in the `codex-config` dependency
before native assertions ran, while shared disk capacity was also exhausted.
Remote source-head CI at `12a3bbb7c74fe0dc78cd6e3e244537ffd96dff1b`
passed cognition, operation-owner (52 tests) and ledger (119 tests) stages.
Its native stage had 36 passed and one failed assertion in an existing real
App Server fixture. That fixture omitted streaming text frames; investigating
it also exposed the completed-message collection defect above. These partial
results do not qualify the later corrected candidate. Final native assertions
and exact source-head/base-merge CI remain pending unless recorded separately.

Source references, added tests and successful declaration checks are not
substitutes for native test execution. No historical receipt, bootstrap artifact
or self-reported counter grants production readiness.

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
