# Original Root resident provider candidate

Status: isolated, unformatted source proposal. Base is `cc57c7198db6293ccca562253c42fffbe2a04633`, tree `b7b357c07b5539769a068c6b9b009629f5612d1e`. No active checkout, native process, source ref, test budget, or qualification result is changed. No Rust compilation, formatter, mechanism test, source gate, or real A/B/C task has run for this proposal.

## Implemented path

The candidate provides an explicit library entry for a trusted provider that already holds all ten connected original role streams. It has two concrete parts:

1. A distinct, single-consumption datagram handoff carries the existing stream/pidfd pairs into the actual Root resident process. It does not parse a provider address, discover a service, reopen an owner, issue a grant, or manufacture a receipt.
2. A concrete Root service consumes the opaque handoff, an existing original Root registration, independently trusted typed inputs, and one existing A/successor connection. It constructs the original Candidate stage bundle, invokes the original Root runtime composition, and runs the original coordinator and command server together.

The new service is a real implementation of the previously unconnected `into_candidate_runtime`, `RootResidentLearningRuntimeV3::run`, and `RootResidentLearningHandleV3::serve_original_stream` path. It is not activated by stock `main`. Stock `main` has no observed provider of the required trusted typed objects and connected capabilities. Adding a command-line callback, an `Unavailable` factory, or a fabricated product caller would not supply those objects, so none is added.

## Eight source files

| File under `codex-rs/hepta-agentd/src/` | Change |
| --- | --- |
| `root_candidate_stage_handoff.rs` | New opaque ten-role handoff, exact purpose/profile/recipient checks, role mapping and original monotonic end |
| `root_candidate_stage_handoff_wire.rs` | New bounded 21-right frame; original two-right frame and its existing eight-FD send bound stay byte-identical |
| `authority_host_learning_candidate_service.rs` | New concrete consuming service and externally supplied typed input/consumer structures |
| `root_candidate_stage_handoff_tests.rs` | Four unexecuted FD-framing and metadata mechanism tests |
| `root_production_handoff.rs` | Private module mount and explicit exports only |
| `authority_host_learning_resident.rs` | Private service module mount and explicit exports only |
| `cell_q24_candidate_stage_owners.rs` | One crate-private, consuming operation that can only reduce the bundle/common deadline before Root installation |
| `lib.rs` | Explicit Linux-only exports; no startup activation |

All existing function bodies remain unchanged. The new deadline operation is needed to preserve the opaque bundle's private deadline fields; the provider never receives mutable access to them. No dependency, configuration file, schema, budget, old assertion, or existing test attribute changes.

The patch is supplied as one review candidate, with two coherent review units: capability transfer plus its negative framing tests, and the consuming Root service plus its original deadline cap. These units should be reviewed separately because the cross-process lifetime and Root supervision rules are substantive. Final line counts and final source fences must be computed after the authorized original formatter; the compact preparation bytes are not final formatting evidence.

## Ten original roles

The ordering is fixed. The first descriptor is the original sender Root pidfd. Each following pair is one already connected stream and the corresponding original owner/task pidfd.

| Slot | Existing typed source | Actor checked against original profile | Original receiver |
| --- | --- | --- | --- |
| Experience | `common.experience` | `initial.owners.experience` | Original Experience material command client |
| Dataset | `common.dataset` | `initial.owners.dataset` | Original Dataset material command client |
| Training | `common.trainer` | `initial.owners.trainer` | Original Training command connection |
| Selector | `common.selector` | `initial.owners.selector` | Original Selection channel |
| Version | `common.version` | Original task peer; no actor invented | Original Version command channel |
| NextUse | `common.next_use` | `initial.owners.next_use_observer` | Original C command channel |
| Completion | `common.completion` | Original task peer; no actor invented | Original C readiness channel |
| Candidate material | `candidate_material` | Same original Trainer actor | Distinct original Training material connection |
| Evaluator | `evaluator` | `initial.owners.evaluator` | Original initially held E connection |
| Model | `model` | `initial.owners.proposal` | Original initially held Model connection |

Every role stream must be a distinct AF_UNIX/SOCK_STREAM object. Reusing the same underlying socket for two purposes is refused even when different duplicated descriptor numbers are presented. Multiple original roles may share a real host process and hence a pidfd identity; the candidate does not invent a requirement for ten different PIDs or ten independent operators.

The old `original_owner_command_channel_v1` and each original typed constructor still validate the actual socket peer UID/PID, process boot/start identity, held pidfd and lifetime. They retain the original same-UID/same-PID refusals. The new packet's process descriptions are comparison inputs, not proof that those checks passed.

Passing an FD does not retarget SO_PEERCRED. A provider must obtain endpoints that were established for the actual Root resident PID. An A-pinned or launcher-pinned role endpoint cannot be made suitable by changing the packet's PID or UID. The recipient PID, boot ID and start ticks are checked against the actual receiving process, and the sender remains pinned by the original unnamed Root pair and pidfd checks.

## Independent trust and purpose

Wire metadata contains only the dedicated purpose, original profile binding, actual recipient identity, ordered role process comparisons, original timeout values, and absolute monotonic ends. Serde denies unknown fields. In particular, the packet has no `fresh` switch, material configuration, evaluator protocol, loaded model, trust-key list, grant, signature, task receipt, result, or reward definition.

The provider separately supplies `RootResidentCandidateInputsV1` containing the existing typed `OriginalCellQ24MaterialReceiptConfigV1`, `OriginalCellEvaluationPanelRegistrationV1`, `Arc<LoadedCellQ24ModelV1>`, and `LearningEvidenceVerifierV1`. The existing original Root registration is consumed by value. Original Root authorization `Check` operations surround admission; the original stage constructors and runtime composition retain their complete initial/scope/trust/model checks.

Fresh versus Recovered is taken from that existing Root registration's private authorization mode. Only the original fresh or original recovery constructor is selected. Wire data cannot promote recovery to work. The existing Root registry/issuer/checkpoint checks remain responsible for every later admission, effect and observation. Existing evaluated 4/5/6-cut and legacy 3/4/5-cut distinctions, Adopt refusal, incomplete-evidence refusal, and NoUpdate semantics are not edited.

## Deadline, consumption and supervision

The sender converts each original lifetime to an absolute Linux `CLOCK_MONOTONIC` end. The receiver rejects expired or excessive values, preserves each timeout, and derives only the remaining duration. The original completion limit stays 500 ms; other command limits stay 30 seconds; every original role remains bounded by 300 seconds. The exact minimum end is also retained as an `Instant` cap and can only narrow the constructed Candidate/common bundle and the service lifetime. A delayed handoff or delayed admission is not permitted to install a later global end.

The opaque handoff and service have no Clone, role getter, writer accessor or retry method. Their ownership paths consume the socket and role descriptors even on failure. This is linearity of these APIs, not a claim that a hostile provider could never duplicate an FD before calling them; the original role request/once-state checks remain necessary.

The service supervises the original server and original Root runtime. A EOF or lost A server handle does not cancel an already admitted Root future. Root cancellation and the finite original end cancel the coordinator and shut down the one server stream, then join the owned tasks. Dropping the service future cancels its child token and shuts down that stream. It does not cancel unrelated Root tasks or peer processes.

As in the original runtime contract, an effect already dispatched remotely can outlive a cancelled await. No timeout or service return is turned into NoUpdate, a refund, or proof of non-execution. Such outcomes require the existing explicit same-operation readback path. The service returns a service-lifetime result, not a learning disposition.

## Concrete provider use and remaining activation boundary

The intended trusted Root host sequence is:

```rust
// Each value comes from its existing original provider, not packet JSON.
let registration = original_root_service.register_resident_learning_v3(profile.clone())?;
let handoff = receive_root_candidate_stage_handoff(inherited_pair, &profile, timeout)?;
let service = registration.into_candidate_service(original_typed_inputs, handoff, original_a_peer)?;
service.run(original_root_cancellation).await?;
```

Cold recovery uses the existing `recover_resident_learning_v3(profile, independently_authorized_readback)` entry instead. The same consuming service then selects only original recovered channels. Neither branch creates the required registration.

A embedding already has `AgentdConfig::with_root_resident_learning_enrollment` and `AgentdRootResidentEnrollmentV3::enroll_original_root`. Its exclusive-mode checks and completed-A outbox join are implemented in cc57. The new service can be paired with a genuinely supplied `AgentdRootResidentLearningClientV3`; it does not create one from a profile digest. There is no observed current `main`/launcher path that supplies this original client plus the ten-role Root bundle and trusted typed materials, so this proposal adds no ungrounded startup flag or source callback.

The remaining external deployment work is concrete: a trusted original provider must arrange the Root-targeted role connections and actual A-targeted Root connection, retain real pidfds, supply the unchanged original trust/material/model objects, deliver the independent Root execution or recovery grant and exact lease, and invoke the explicit APIs. Their authentic instances have not been supplied in this session. A/B/C outcomes, model availability/license evidence, cost-ledger completeness and recovery observations therefore remain Unknown; the demonstrated real task-chain count stays zero.

## Before this can be a qualified source

`STRUCTURAL_REGISTRATION_PLAN.json` identifies the five genuine new product-call edges in existing closed boundaries and the new public/opaque entry points needing protection. The current cc57 CALLERS file, all 569 boundaries and all 422 protected rows are untouched. The old empty caller arrays cannot be left unchanged if this source is later adopted, but they also cannot be changed to claim a caller before the implementation is in that exact source.

Root must arrange isolated peer review, original scoped fix/fmt, exact postformat fence/QA/allowlist work, mechanism and integration verification, and the unchanged original source/native gates. `VALIDATION_DESIGN.md` specifies required normal and refusal coverage. The four new source tests are merely prepared; none has run. No old cc57 result is inherited by this candidate.
