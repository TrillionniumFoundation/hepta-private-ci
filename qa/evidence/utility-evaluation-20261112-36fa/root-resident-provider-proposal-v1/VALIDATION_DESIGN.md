# Verification design for the original Root provider candidate

This is an unexecuted verification design, not a run record. Current native qualification belongs to cc57. This candidate has no compiler, formatter, test, source-gate or real-task result.

## Prepared tests in this patch

Four tests in `root_candidate_stage_handoff_tests.rs` use real anonymous sockets and actual SCM_RIGHTS transfer. The deliberately synthetic framing profile creates no original role authority.

| Prepared method | What its assertions establish if it later passes | What it cannot establish |
| --- | --- | --- |
| `candidate_wire_preserves_all_original_fd_objects_and_cloexec` | Every received FD reaches the same ordered connected object after originals drop; every FD has CLOEXEC | Original Root pin, role identity, authorization or task success |
| `candidate_wire_and_old_two_right_packet_cannot_consume_each_other` | Exact old/new packet separation and received-FD cleanup on both refusal paths | Legal role provider or registered Root custody |
| `candidate_wire_rejects_role_socket_alias_and_closes_all_received_rights` | Duplicating a socket into another role is rejected and all transferred rights close | Independence of different PIDs or evaluators |
| `candidate_packet_refuses_changed_binding_role_process_and_original_timing` | Bound purpose/profile/current recipient, exact role list/order, finite timeout/end, and no wire-origin field | Cryptographic trust, live role servers or a real A/B/C run |

The positive wire test intentionally uses stream objects in every raw FD slot so it can test the generic wire in an ordinary unprivileged run. It does not call the public Root receiver or pretend those stream objects are pidfds. Only the full original admission path validates actual pidfds and role processes.

## Required integration cases before landing

The integration harness must use original owner implementations and their real connected streams. It must not replace stage methods with canned receipt DTOs, manufacture a successful current pointer, weaken the original same-UID/PID checks, or substitute an already-bound E Client for the pre-held E Connection. Where test-only original owners issue controlled fixture signatures, results must be described as mechanism results. No fixture is evidence of a user's real task, independent B result, model license or deployable utility gain.

The existing original Root fixture locations are pinned in `SOURCE_REFERENCES.json`:

- `authority_host_learning_resident_root_support_tests.rs` / `ResidentRootFixture` provides the existing explicit Root registration/recovery test machinery.
- `authority_host_learning_resident_root_tests.rs` already covers original vacant CAS, exact lease/grant revocation and lost-fresh-ACK readback boundaries.
- `authority_host_learning_resident_transport_tests.rs` contains bounded original wire cancellation/uncertain-response mechanisms.
- `root_production_learning_handoff_tests.rs` shows the existing actual UID0/dedicated-UID descriptor qualification conventions. Its two-right protocol and cases must remain unchanged.

These helpers are not a ten-owner provider. The new end-to-end integration fixture must arrange the actual original material/Training/Evaluation/Model/Version/Selection/NextUse services with Root as the actual peer, and retain each role's original state for readback assertions. If that fixture cannot be completed with existing original APIs, the gap remains a blocker; none of the four framing tests substitutes for it.

| Case | Required action and expected boundary |
| --- | --- |
| Fresh complete NoUpdate normal route | Use a controlled completed-A source, genuine fixture Root execution grant+lease, trusted full material/protocol/baseline/verifier, ten distinct original streams, and actual A peer. Invoke public send/receive/service APIs; enroll the actual Root client through existing late enrollment. Observe the original T, independent fixture B, complete Ineligible/NoUpdate, actual Version publication, S, C and six signed cuts. Do not assert success from service return or enrollment ACK. |
| Existing candidate refusal route | Use candidate data whose comparison cannot be completed or whose original Adopt/FinalUse permissions are absent. Expect the original Unknown/OwnerUnavailable route, retained parent version and no unauthorized C. Do not insert a fallback NoUpdate. |
| Recovered Root normal observation | Finish/persist the controlled operation, dispose fresh custody, obtain an independently authorized readback registration and new original recovered connections. Public service construction must select recovered stage constructors; exact previous cut/current material readback may succeed, but fresh Admit must remain refused. |
| A disconnect after actual admission | Disconnect A only after observing the original Root admission/dispatch boundary. Keep Root cancellation live. Confirm the original Root operation continues or preserves an uncertain checkpoint according to original owner outcomes; A EOF alone must not create a second operation or cancel Root. |
| Root cancellation during work | Cancel only the Root child token after a known original boundary. Original server closes and owned tasks join; any dispatched-but-unobserved effect remains Unknown and requires explicit readback. No replay, automatic reconnect, synthetic refund or clean NoUpdate. |
| Deadline during transport/admission | Delay the handoff or defer construction past its original monotonic end. Refuse admission and close all rights. At a nonexpired delay verify the installed global end is at most the original end, never a fresh 300-second window. |
| Deadline after dispatch | Exercise a real original effect near the cap. Preserve original explicit uncertainty if an effect outlives the await; no late successful comparison may be inferred from the service ending. |
| Wrong target process | Send otherwise valid role capabilities with another recipient PID, changed boot ID or changed start ticks. Refuse before original role construction. A descriptor copied to an A/launcher peer cannot be repaired by metadata changes. |
| Wrong role peer/pidfd | Swap two distinct role sockets, replace one pidfd with an unrelated live process, provide dead pidfd, wrong UID/PID/start/boot, or same-process/UID endpoint. Original constructors must reject; no new receiver may fall back to trusting the JSON. |
| Wrong independent typed inputs | Change material scope, evaluator protocol, baseline components, verifier trust digest or original Root binding independently. Reject through the existing original material/profile checks. Keeping packet profile text equal is not sufficient. |
| Lost/malformed handoff | Send missing/extra/truncated rights, oversized/empty body, unknown fields, wrong purpose, duplicated socket, wrong role count/order or expired end. Reject and close all received rights; sender-consumed values have no retry method. |
| Exactly-once and recovery separation | Repeat admit on the same actual connection, close after dispatch before reply, recover with the separate readback grant, and attempt fresh work through recovery. Retain original once-state/cut/current checks and refusal semantics. |
| Original authority changes during admission | Revoke the exact Root lease/grant between the two original `Check` calls, or change original source/current data before later stage dispatch. Refuse with original checks; metadata, old successful checks and Root UID do not grant authority. |
| Existing configuration exclusion | Keep the original `with_root_resident_learning_enrollment` mutual exclusions against direct learning/bootstrap mode and missing Circuit/Objective/authbus source. A provider wiring change must not silently enable both branches. |

## Source protection and original gates

After original scoped formatting, register only the actual five new calls documented in `STRUCTURAL_REGISTRATION_PLAN.json`, add the new handoff/service boundaries and full-function/literal fences, and update the corresponding existing exact-set QA. Preserve all previous caller membership, authority flags, negative cases and protected bytes that are unaffected. Complete-source collection must include every Rust source; tests/examples are excluded only by the existing product-caller predicate.

Necessary new source mutations include deleting either Root `Check`, swapping Fresh/Recovered constructors, bypassing the bundle deadline restriction, removing actual peer/pidfd checks, changing the exact purpose or role order, allowing duplicate role sockets, making the opaque handoff Clone/publicly constructible, trusting a wire-origin value, cancelling Root on A EOF, or invoking run/serve from a new unregistered path. Every mutation must fail the appropriate original validator or actual behavior test rather than merely change a score.

The final native plan must use the unchanged original phase commands, budgets, 8 MiB stack defaults, default ignored-test behavior and explicit Root-case inventory. If new actual UID0 integration cases are added, list their complete FQNs in that inventory instead of counting ignored cases as passed. No retries, extended timeouts, partial-source substitute or inherited cc57 PASS is proposed here.
