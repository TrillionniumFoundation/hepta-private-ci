# E3: one late Root enrollment through the original daemon outbox

This is a local, unformatted, uncompiled source proposal. It succeeds the frozen `root-service-layer-v1` packet `0dc5e98ff38ed0c4c4defe277d21a5cb90bae37b`. It does not overwrite that layer. No H process, Rust execution, formatter, source gate, QA, source Git object or ref operation was performed by this author.

## Concrete normal path

The original production launcher accepts one additional `--root-resident-learning-handoff-fd`. It includes this FD in the original pre-ownership duplicate check and adopts it before Config opens files. The old V1 learning flag and this V3 flag are mutually exclusive. Existing ordinary/Android/Notes/Desktop flows remain; the new field is optional.

The daemon still drops to its actual dedicated UID through the original launcher. It starts the original `crate::run` and delivery actor while waiting for the late packet. The exact original `with_root_resident_learning_enrollment` guard remains untouched, including the requirement for actual Circuit bootstrap and invocation, Objective profile and AuthBus trust. E2 must first install its actual task Config; a missing task cannot be made successful by this layer.

Once ordinary A has really completed, Root runs `serve-resident-learning-late` or the distinct `recover-resident-learning-late`. These commands accept the first layer's config/deployment/trust/model/ten-role stage inputs plus a separate enrollment datagram and the original held Root pidfd. They do not accept a pre-drop consumer stream. All inherited numeric slots are adopted before file opens/runtime construction. The new Root process must itself be the retained creator of the inherited anonymous Root datagram; a different child or proxy is rejected by the original `root_pair` predicate.

Root uses the same concrete `HostAuthorityServiceConfig` for its original open-only issuer/Registry/Root factory and listener custody. The new code does not reread that path between recipient selection and original registration. Fresh and readback dispatch use the unchanged actual `RootResidentLearningRegistrationV3` constructors; the packet cannot change the registration's origin. Registration precedes public enrollment delivery. A later failure does not imply the durable Root record was unwritten.

The listener lives under the original Root-controlled `root:peer-gid` mode `02710` runtime parent. It calls the unchanged original `validate_lane_paths`, creates a new socket without unlinking an occupied path, retains an exact inode guard, and verifies mode `0660`, Root ownership and peer group. Its fixed name uses a 128-bit prefix of the full profile binding only as a bounded rendezvous name. Authentication uses the complete profile and exact device/inode, not that shortened name; any occupied-name collision fails closed.

The new fixed V3 marker transfers exactly two rights: a Root-owned sealed mode-0400 memfd and the same Root's actual pidfd. The original descriptor bound and seal validator are unchanged. The private packet contains public profile input, the exact independently loaded Root trust data, signed original intent/lease, explicit fresh/readback purpose, recipient UID/GID/PID/boot/start, Root identity, socket node identity and absolute monotonic deadlines. It contains no LedgerWriter, Source publication, stage signer/private key, execution token or owner capability. The root-owned trust input is an explicit operational trust source, not proof of scientific independence or actual completion of A.

After receipt, the daemon verifies the actual recipient, Root pidfd and process identity, profile reconstruction, verifier digest and socket custody. It connects once after dropping credentials. This matters because Linux records stream credentials at connection establishment: inheriting a Root-created connection cannot manufacture the daemon's UID. The original `f42d9f...` command channel independently enforces real SO_PEERCRED, PID, boot, start, pidfd lifetime and its same-UID/same-PID refusal. That file is unchanged.

The resulting actual V3 client goes only to `AgentdRootResidentEnrollmentV3::enroll_original_root`. The unchanged delivery actor rechecks the real A source, current owner, exact outbox request and Root readback. It alone writes the durable learning claim and chooses original Admit versus readback. The new launcher implements no claim, stage loop, fake ACK, checkpoint, retry, signer or replacement connection.

## Timing and lifecycle

The passive wait for A's late packet is bounded by the original production session end, at most 300 seconds, captured before original Root connection setup. It is not a restarted handoff timeout. A received packet has a separate absolute CLOCK_MONOTONIC handoff/accept deadline of at most 30 seconds, checked before and after construction, and a session end of at most 300 seconds. Translating clocks samples `Instant` first, so translation can only shorten the remaining interval. The connect is additionally bounded by 500 milliseconds. Original command timeout, four-permit role budgets, 128 requests and signed grant/lease windows are unchanged.

The Root wrapper retains the exact pathname guard through the original service lifetime and adds a cancellation cap at the same captured session end. The original service still closes and joins its owned work. This is not a claim that every internal relative HAP `Instant` is numerically identical, nor that a remote effect already dispatched is rolled back by cancellation.

No receive thread or accept thread is detached: both new waits use nonblocking Tokio I/O. Dropping an unreceived handoff closes owned descriptors. The daemon's ordinary runtime future is never dropped merely to hide an enrollment error; failures are logged immediately and returned after the original runtime finishes. A daemon exit with the local enrollment ACK still pending returns an explicit unknown error. An observed local enrollment ACK still is not a learning completion ACK. The existing Root continuation may outlive A/daemon EOF.

Root CLI SIGINT/SIGTERM during preparation closes local inputs/listener and reports that same-operation readback is required. It does not reconstruct fresh custody. After service start it requests original cancellation and awaits the original service. Arbitrarily cancelling an API caller's own future does not become a terminal-worker proof.

## Tests and limits

Five new methods are source only, with zero execution. Three ignored UID0 methods exercise actual memfd seals, SCM_RIGHTS framing and pidfd validation: exact purpose/bytes, V1-marker rejection, and a duplicated sealed file in the pidfd slot. Two ordinary methods exercise absolute deadline translation/refusal without sleeps. The framing-positive case deliberately carries no valid profile and stops at framing; it is not a successful service, owner or enrollment test.

Full cross-UID normal enrollment, actual outbox claim/ACK, cancellation, service recovery and the complete ten-owner chain still need real integration fixtures and the original gates. This layer does not fix the missing Material Source edge: E2 owns the future purpose-fixed readonly Source loan from the same actual Root Source to a non-Root Material process. Root's same-UID command prohibition remains intact. E/D/Trainer/B/Evaluation/Version/S/C/Model owners and their original signed inputs must come from their real legal factories; this transport does not manufacture them.

## Integration and registration obligations

Root alone must compose the independent E2 task-launcher insertions with these explicit splices. E2's task Config installation must precede the new V3 opt-in. E3 adds no E2 runtime/driver/cell/source changes.

CALLERS, protected scopes, exact Root parent inventory and allowlists have not been updated or executed in this layer. The three ignored tests require explicit original parent registration; the new production boundaries, private trust reconstruction and their real callers must be collected by the unchanged scanner. No collector/QA/Rust/native result is inferred from Python byte checks. All new helper test files end in `_tests.rs`.

All identities in this local manifest are computed, unless an individual reference's original Git readback is explicitly recorded. Root may subsequently preserve or integrate this frozen proposal; this author does not claim to have published it.
