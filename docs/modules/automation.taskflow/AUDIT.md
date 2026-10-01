# automation.taskflow adversarial audit

This stable audit guide records failure mechanisms, repaired invariants, regression locations and remaining implementation boundaries.
Git history preserves prior revisions. Current candidate identity, test results and pull-request status are supplied only by exact-candidate Git/CI evidence; this document is not an execution or activation receipt.
Primary owner: `automation-platform`; Agentd composition co-owner: `agent-runtime`.
Contracts, write domains and authority ceilings remain those of the canonical registries.

## Scope and method

The audit compared [the technical guide](TECHNICAL.md), [the execution dossier](../../../qualification/module-execution-dossiers/detail/automation.taskflow.md), `docs/DEVELOPMENT.md`, module/source/readiness registries and `CALLERS.toml` against native source and tests.
Source scope included `hepta-automation`, Agentd scheduler/recovery/effect-host control and the HTTP provider-effect transport.
Reviews separately covered authority/payload/provider identity, durable crash/restart state, program progression and runtime/product composition.
Adversarial cases included forged decoded fields, expired/stale fences, uncertain provider contact, lost replies, terminal crash cuts, retirement and calendar/profile boundaries.
Real SQLite reopen cases and bounded mock-provider tests are source checks; they do not establish deployment or an independently qualified provider.

## Completion by layer

| Layer | Implemented source | Remaining completion boundary |
| --- | --- | --- |
| Development documentation | Detailed guide, native implementation map and execution dossier | Keep source/host/schema truth synchronized and verify the committed candidate |
| Timer/calendar owner | Once/interval compatibility, Calendar V2, frozen revisions, deterministic occurrences and timer writer epochs | Authentic/current IANA profile and selected-host DST, races and capacity evidence |
| Agentd/Codex composition | Existing scheduler, stable queue reconciliation, durable turn observation and TaskFlow terminal propagation | Selected-host execution/restore qualification |
| TaskFlow ledger/outbox | Bounded definitions/runs/events, fenced step intent/receipt history and unresolved-work barriers | General DAG execution and trusted predecessor facts are not supplied by the ledger alone |
| External-effect seam/host | Signed final-use binding, immutable attempts, versioned provider keys, new-attempt contract pinning, optional configured HTTP host and explicit status control | Legacy unbound configuration continuity, safe automatic rotation and arbitrary scheduled-effect workflow composition |
| Neural Circuit candidate | Typed bounded compiler and exact-predecessor successor validation | Actual DecisionCells/organ ports, direct ingress, joins, feedback, subcircuits, cancellation and runtime fairness |
| Production status | Source root exists; ordinary source composition is present | `production_implementation`, product execution, independent acceptance, activation and release remain false |

TaskFlow remains the durable execution foundation within the existing CNS.
Timers decide when to wake a scheduled run; Agentd/Codex and registered effect owners retain their execution responsibilities.
No second scheduler, daemon, authority issuer, domain writer or universal state store is introduced.
The timer's built-in workflow is `codex_turn`; configured HTTP execution requires an already claimed/prepared effect step.

## Fixed findings and regression locations

Priority P1 denotes a correctness, authority or availability boundary; P2 denotes narrower liveness or documentation accuracy.
The locations below identify source fixes and executable regressions, not independent acceptance evidence.

| ID | Priority | Failure mechanism and resulting behavior | Owning source / regression |
| --- | --- | --- | --- |
| AF-01 | P1 | Forged/stale claim tuples or mutated payloads could reach materialization/preparation; durable claim, canonical instant/revision and prompt/thread now revalidate before outbox creation | `lifecycle.rs`, `automation_taskflow.rs`; `occurrence_materialization_rejects_stale_and_forged_claims`, `preparation_rejects_payload_mutated_after_materialization` |
| AF-02 | P1 | Unknown/claimed step work could be abandoned through progression, takeover or another attempt; latest unresolved steps now block those mutations transactionally | `taskflow_guard.rs`, `taskflow.rs`, `taskflow_step.rs`; `tests/taskflow_step.rs` and authorized-effect crash cases |
| AF-03 | P1 | Decoded constructor-placeholder definition digests bypassed canonical validation; serialized registration now requires the computed digest | `taskflow.rs`; `registration_rejects_constructor_placeholder_before_writing` |
| AF-04 | P2 | Saturating successor arithmetic admitted a repeated maximum version; checked version+1 now rejects overflow | `neural_circuit.rs`; `saturated_version_cannot_admit_same_version_successor` |
| AF-05 | P1 | Retirement could strand admitted execution; API, SQL trigger and reopen checks now reject admitted/running/indeterminate work | `timer_lifecycle.rs`, migration `0020`; `retirement_waits_for_lifecycle_settlement_while_handoff_preserves_it` |
| AF-06 | P1 | Provider identities lacked owner isolation; new v2 keys bind owner/run/step while persisted v1 attempts retain original recovery keys | `authorized_effect.rs`, `effect_dispatch_ledger.rs`, migration `0021`, Agentd host; `provider_identity_is_owner_scoped_and_preserves_historical_recovery` |
| AF-07 | P1 | Effect entry lacked exact live-lease admission, stale recovery could append evidence, and writer/final-use waits could admit with a pre-wait timestamp; logical entry time plus monotonic elapsed time now revalidates at writer admission and inside the authorized consumer immediately before driver contact, while historical recovery checks its exact fence | `authorized_effect.rs`, `effect_dispatch_ledger.rs`, `tests/authorized_effect/effect_admission_tests.rs`; expired-lease, stale-recovery and four sync/async writer/consumer-wait regressions |
| AF-08 | P1 | Host synchronous thread joining blocked runtime progress; native async dispatch now retains the final-use active fence without the join | Agentd `automation_effect_host.rs`; `host_dispatches_exact_wire_payload_once` |
| AF-09 | P1 | Same-frontier revocation contents, raced file reads and unbounded HTTP body buffering weakened trust/capacity checks; full-head equality, capped stable-file reads and <=65536-byte streamed responses now reject drift/oversize | Agentd host and `model-provider/src/provider_effect.rs`; host/provider source tests |
| AF-10 | P2 | One unresolved occurrence could monopolize observation; successful still-pending snapshots now rotate with exact CAS, and queue/turn observations have a 5-second deadline | `occurrence_observer.rs`, Agentd `automation_recovery.rs`; `completed_observations_rotate_work_without_overwriting_newer_state` and timeout regression |
| AF-11 | P2 | Calendar resume bypassed canonical timing/forbidden overlap; finite delayed coalescing incorrectly depended on an expired profile reference | `schedule_v2.rs`, `lifecycle.rs`; resume/finite-profile regressions and `disabling_and_resuming_cannot_bypass_forbidden_overlap` |
| AF-12 | P1 | Terminal crash recovery could reinterpret a settled step, and pre-step reclaim compared differently scaled generations; exact terminal receipt/outcome and same-unit generations now govern recovery | `automation_taskflow.rs`; `terminal_recovery_cannot_rewrite_a_settled_historical_step`, `pre_step_crash_reclaims_using_taskflow_generation_units` |
| AF-13 | P1 | Scheduler detachment could remove explicit external-effect recovery along with admission; Agentd retains a recovery-only store while new execution remains disabled | Agentd `state.rs` / `state_control.rs`; `host_dispatches_exact_wire_payload_once` exercises detached control reaching exact-attempt validation and denied new execution |
| AF-14 | P2 | Guide/dossier stopped at schema16 and denied an existing configured host; documentation now reflects the current schema, actual control composition and layered completion | `TECHNICAL.md`, execution dossier and native mapping |
| AF-15 | P2 | The inherited map anchor was not an ancestor of the inspected candidate; a scoped fresh navigation review now binds current source objects and explicitly retains the superseded identity/reason | `IMPLEMENTATION_MAP.json`; development navigation verification, without transferring executable acceptance evidence |
| AF-16 | P1 | Recovery recomputed host identity from current configuration; new HTTP attempts now persist immutable scope/attested-contract binding before contact and reject changed remote recovery, while already durable terminal evidence remains locally recoverable | migration `0022`, authorized-effect ledger and Agentd host; durable binding/reopen and scope/reattested-endpoint drift regressions |
| AF-17 | P2 | String parsing rejected the IPv6 loopback HTTP fixture; typed URL hosts now accept loopback addresses while retaining HTTPS for non-loopback destinations | `model-provider/src/provider_effect.rs`; `attested_http_adapter_accepts_ipv6_loopback_fixture_only` |
| AF-18 | P1 | The directly consumed durable operation kernel sampled time before writer admission, allowing queued writes to falsely report clock rollback or renew an expired lease | `hepta-operations/src/durable_store.rs`; held-writer, true rollback and delayed-renewal regressions |
| AF-19 | P2 | Calendar search assumed local-label order matched UTC order, missed midnight rollbacks and inclusive profile boundaries, and scanned past finite ends; UTC envelopes now bound both directions and unsupported triple overlaps reject at validation | `schedule_v2.rs`; midnight, adjacent-transition, finite-end and three-way-overlap regressions |
| AF-20 | P1 | A cancelled, disabled, expired or non-running occurrence could cross the first queue-contact boundary; exact current task/run/claim and both lease horizons now guard first intent, with monotonic elapsed time at the scheduler contact cut | `store.rs`, `scheduler.rs`; first-intent and delayed-preparation regressions; existing uncertainty remains historically recoverable |
| AF-21 | P2 | Expired local claims could roll lifecycle identity before settling the old step; safely cancelled backlog could retain an orphan Claimed lifecycle and permanently freeze schedule policy | `automation_taskflow.rs`, `taskflow_step.rs`, `taskflow.rs`, `lifecycle.rs`; exact attempt/fence and independent-contact barriers, expired-claim and disable/resume regressions |
| AF-22 | P1 | A recording command collision could leave an already-sent effect without a writable projection; contradictory recovery could poison immutable evidence before terminal-step validation | `authorized_effect.rs`, `effect_dispatch_ledger.rs`, `taskflow_step.rs`; pre-contact command uniqueness and atomic terminal outcome/receipt guards in both write directions |
| AF-23 | P1 | Status NotFound was treated as proven absence, and Accepted admission was lost when flattened into an opaque indeterminate receipt; typed initial status and dispatch/lookup acceptance witnesses now preserve admission across restart. Known Accepted excludes both later rejection and proven absence while allowing terminal execution observations | migration `0023`, authorized bridge and HTTP host; NotFound quarantine, `lookup_acceptance_survives_reopen_and_cannot_become_rejection_or_absence`, `rejected_lookup_distinguishes_unknown_accepted_and_legacy_dispatch` |
| AF-24 | P2 | Agent draining blocked current-generation historical recovery; the narrow recovery gate now permits settlement while preserving critical/revocation readiness, exact generation and denied new execution | Agentd `state_control.rs`; draining recovery, stale generation and execution-denial assertions |
| AF-25 | P1 | A regular configuration file replaced by a FIFO before open could block the host; Unix open now uses NOFOLLOW/NONBLOCK and rejects nonregular descriptors | Actual shared `automation_protected_file.rs` and sibling tests; isolated runtime target reads the same production source |
| AF-26 | P2 | The focused CI only watched an obsolete branch, and documentation used a dated status file with an incomplete owner write envelope | `.github/workflows/automation-taskflow-focused.yml`, stable `AUDIT.md`, work packages and guide; relevant-path PR/main triggers, locked repository test runner and precise host source registration |

Permanent retirement is stricter than compatible handoff, but does not erase a safely stopped backlog.
Provider-proven-absent pending/claimed work can remain behind its tombstone after leased/uncertain drain; it cannot admit a new provider effect.
Schema19's pre-existing migration convergence preserves recognized SQL/checksums and rejects unknown, dirty or conflicting historical identities.

## Repeat-review method

Compare documentation and registries to actual callers, then review identity/authority, durable lifecycle, progression and host execution independently.
After each coherent source repair, re-read the combined changes at pre-contact, lost-reply, terminal-persistence, cancellation, retirement, reopen and compatibility cuts.
Exercise concurrent writer admission, exact command/attempt identity, historical provider lookup, scope/contract drift and timezone boundaries through their owning native APIs.
Run affected-package regressions before repeating the adversarial review. Stop a review round only when no new concrete defect remains in that inspected scope; record unresolved implementation and evidence boundaries separately.
Review convergence is bounded by scope and evidence. It is not a claim that no bugs or future optimizations exist.

## Remaining implementation work

- A general TaskFlow/Neural Circuit runtime still needs actual DecisionCells, organ calls, event ingress, joins, feedback, subcircuits, cancellation and fair conserved budgets.
- Signed dependency/compensation descriptors bind bytes; the effect seam does not independently prove predecessor completion. Product owners must obtain trusted predecessor receipts.
- External-effect recovery is explicit Agentd control. The scheduled observer reconciles ordinary Codex queue/turn occurrences; it is not a generic external-effect backlog worker.
- New configured HTTP attempts pin the original provider scope and attested contract digest. Changed remote lookup rejects; original configuration bytes are not retained or automatically restored. Legacy/generic `NULL` bindings require original key/status-lookup continuity or must remain unresolved; a safe automatic rotation protocol is unfinished.
- Historical v1 keys retain their original delimiter/tenant ambiguity. Recovery must investigate provider-specific identity collisions rather than invent a unique identity after contact.
- A terminal provider observation persisted before ledger settlement requires exact-attempt reconciliation; an unknown outcome never becomes safe redispatch through restart, cancellation or configuration change.

## Remaining target-host and independent evidence

- Independently provision final-use trust/revocation and provider contract/terminal-observer configuration for each activated effect.
- Bind authentic/current timezone provenance, DST behavior, multi-scheduler races, restore and sustained backlog/capacity measurements to the selected host.
- Measure queue age, latency distributions, memory/storage growth and recovery work; source ceilings are not measured SLOs.
- Obtain independent acceptance and activation decisions; promotion/release remain separately governed.

## Candidate verification requirements

Resolve the source head/tree, current base and any prospective merge from fresh Git/CI receipts. Attach command outputs and their exact candidate identity to the review; do not cache live results or pull-request state here.

| Check | Required evidence and interpretation |
| --- | --- |
| `just test -p codex-hepta-automation --offline --locked` | Execute the affected owner package, including migrations, lifecycle and effect regressions. |
| `just test -p codex-hepta-automation --features taskflow-structural-qualification --offline --locked` | Execute the feature-gated kernel/step qualification cases; compilation alone does not pass them. |
| `just test -p codex-model-provider --lib --offline --locked` | Execute provider transport/status validation when that owner changes. |
| `just test -p codex-hepta-operations --lib --offline --locked` | Execute durable operation regressions when the consumed kernel owner changes. |
| `just test -p codex-hepta-agentd --lib --offline --locked` | Execute actual runtime composition/recovery cases; a dependency build failure leaves them unexecuted. |
| Scoped `just fix`, `just fmt` and whitespace | Apply repository-required lint/format checks; static test-target type-checking does not execute tests. |
| Privileged caller verifier | Run its self-test and source verification after final-use/caller changes. |
| Readiness, module docs and implementation maps | Run development-profile navigation checks on the committed candidate; they do not requalify historical execution or acceptance evidence. |
| TaskFlow exact source observation | Bind the current source paths/blobs and owner callers through the scoped native map. Retain superseded non-ancestral provenance with its reason; never transfer old execution evidence to a fresh navigation observation. |
| Selected-host/provider qualification | Supply independent provisioning, restore, authority, authentic timezone and performance evidence before activation. |

Separate a failed regression from a build failure, a skipped step and a passed check. Earlier failures in an aggregate job can prevent the TaskFlow commands from executing at all. Inspect the exact failing owner and baseline source before attributing an aggregate failure to this module; required checks remain unsatisfied until their current candidate receipts pass.
Verify inherited map ancestry against the current candidate. A scoped TaskFlow navigation repair must not refresh or promote independent module observations. Whole-repository qualification remains governed by each owner's exact evidence.

## Operational continuity

Keep existing Agentd ownership, private per-Agent storage and kernel authority; do not add another execution spine to close an integration gap.
Preserve schema23, immutable observation/reconciliation and provider admission history, provider-key version/contract binding, stable queue identity and unresolved effects during rollback.
Use a newer fenced compatible owner for handoff; do not revive predecessor handles or restore an old database over current receipts.
Retain provider status access for pending effects before changing configuration or removing admission; control recovery does not authorize new execution.
