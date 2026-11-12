# Root resource retirement: scope, custody, default path, and static component evidence

## Status and exact application chain

This is an isolated future source slice. It has not been compiled, formatted, executed, or passed through the original checker. No branch, ref, native process, CI gate, permission, key, or original acceptance count was changed.

The application chain is the original future CLI packet `c43a53a8c41002c6f7cc3687f03cf1209e7dfcd2`, its mechanical rebase `da0c2dfb21cfa5cfe3d6adfa450751bc415a644f` and source binding `609c9cbf86426b3c3db1d313634f64bbd5acd055`, then retirement source packet `27877fffb867deb92360d1e22ae7fc227eb1fc94`, then delta `527fc3d10d856c4ed7e1816907c08e086ba153e6`, the one-operation explicit-owned-type successor `fea83cbd505a56ee76ec7953501eb24ad756568e`, the one-operation None-compatibility component successor `1d287a5958a1411e67a0bfc0a0517d46ed3228e5`, and the confirmed ACK/exit-ordering correction `b9453e40d5c4c01b0ada35b5e482582254c3283e`. These retirement packets contain 33, 5, 1, 1 and 3 exact reversible operations respectively. The resulting slice has 21 production source paths and two component test sources, with ten new tests. The older packet is retained unchanged as history.

The retirement base is `3dbffb487de65a7c598a92510d081855d8b052dc` / tree `8ad6fd006dbe6b514e5f014e2a12bb50334c08c4` plus those future CLI overlays. This is not a replacement tree for the current native candidate `b399a82f5bbf53fe270e477bd90ccd2cdedcdebf`; its Rust is unchanged from `53ed651d9bbaac6b6c0500d390b730f5910a2fa2`. The Model transport successor explicitly preserves that candidate's actual UFCS postimage `be12430d78451c75c29b7d295bba4ea0459155de`; the other current changes and runtime's independently owned pure DTO exports must be combined by exact operation, never overwritten with an old whole parent file.

## What the finite result means

Only the explicit, Root-owned `root_worker_retirement: "original_root_workers"` deployment choice enables this path. Its complete canonical descriptor bytes are retained by the original Root metadata reader, including UID/mode, single-link, descriptor/path stamp and digest checks. Unknown fields and unknown enabled enum values are rejected. Absence and an explicit null for this known optional field both mean disabled None; neither authorizes retirement. In that branch the original MetadataFile bytes and their complete descriptor digest are retained unchanged, with no parse-and-reserialize canonical check. The Serialize attribute omits None, so auxiliary serialization is exactly the original five fields and does not inject a null. Only Some(original_root_workers) performs the complete canonical-byte comparison against the held original descriptor. The field and its exact original input representation remain covered by the complete deployment descriptor digest; it does not create a new signed credential or change the approved Initial, Prepared profile, model, Selection, CURRENT, or FinalUse validators.

The first retirement ACK authorizes the retirement of resources in this particular Root serving scope. The second ACK says that this same Root has joined its actual workers and still holds the returned owners. Neither ACK proves a C effect, an authenticated Outcome, a terminal learning checkpoint, a daemon task join, writer-lock release, daemon exit, or Root OS exit.

A daemon caller is still required to combine its own real C/source/cell/ledger, durable learning and delivery, route/slot, circuit, and session custody before using this path. Wire decoding creates data only. This packet has no decoder-to-completion-cap constructor and does not remove the current daemon Startup failure on unproved completion.

## Exact wire and one-shot cut

The private wire purpose is `hepta.same-actor-q24-deployment.root-retirement.v1`, defined in `same_actor_q24_root_retirement_protocol.rs` at `77cba7adc7a61b0177306a56ad608229e9d56d65`. The original connected progress stream remains the sole terminal stream; it stays registered in the same Gate until the final response and the subsequent EOF-only ordering wait have completed.

| Stage | Bound input and actual precondition | Result |
| --- | --- | --- |
| Existing three progress stages | Full original phase, identity, Root and consumer UID/PID/boot/start lifetime, original BOOTTIME end; Root independently validates approved material and its actual registration ACK | Original behavior and actual registration correlation |
| Sequence 1: AuthorizeRootRetirement | Exact retained CURRENT registration and actual CURRENT request; all eight actual purpose lanes registered; no active admitted exchange; no previous intent or EOF | Root stores one intent under the same short mutex used by request admission, then sends the bound ACK |
| Required business lane EOF | The original peer channel returned exactly `Ok(false)`; same live peer/pidfd and original Gate; prior authorized intent | Actual channel, pidfd and shutdown alias are returned in a private owning bundle |
| Root worker joins | Actual scoped thread handles, all five lanes, Initial, Learning/Model/Publication, host registration and material bridge have returned; original returned owners remain retained | Private joined bundles; no result can be built from a counter or request digest |
| Deadline watcher | Its private stop input requires the actual host/bridge joined bundle; the watcher observes this input and its real handle is then joined | Private all-workers bundle |
| Sequence 2: ObserveRootWorkersJoined | Same original peer and deadline, exact sequence-1 digest, original CURRENT correlation and the actual all-workers bundle | Final Root-only join ACK; keep the actual peer and returned owners alive |
| Final peer release | After the unchanged ACK2 postchecks, read exactly one byte on the same stream using only its original owner.end; zero requires the original peer/end postcheck and any byte is InvalidRequest | Orders Root resource release after a correctly implemented client finishes its response postchecks and closes its aliases; EOF itself proves neither consumption nor C completion |

A busy sequence-1 request refuses immediately. It does not wait for activity to drain inside the original 500 ms exchange or capture a later request start. Request admission remains held through the original response frame. Once sequence 1 reserves its intent, no further business exchange can enter. ACK loss is uncertain and closes the common Gate; it never rearms the intent or grants another lifetime.

The original peer channel continues to bound every frame by the original request start and the already captured end. No remaining-duration-to-new-deadline conversion is added. The deadline watcher runs until the real Root business, registration, and material workers have joined; final exchange checks and the subsequent EOF-only read still use the original lifetime after the watcher joins.

Ordinary EOF, malformed or partial frames, previous errors, peer death, deadline expiry, and poison remain errors. Only the specific lane's actual clean EOF after authorized retirement is accepted. A clean EOF is still not a join witness: the enclosing scope joins that lane's actual thread before constructing its owning bundle.

## Retained resources and actual release order

The following are ownership facts of the source, not observations of a completed deployment. Rust field declaration order is used for the bundles that retain the original service last.

| Real resource | Actual owner after its worker returns | Required event before release | Failure behavior |
| --- | --- | --- | --- |
| Five original authority channels, their pinned owner descriptors and shutdown aliases | `OriginalRootAuthorityLanesJoined.channels`, with the actual `BoundLanes` retained | Each exact original thread joined; bundle retained through final ACK | Armed closing guards keep common shutdown responsibility |
| Learning, Model and publication channels | `OriginalRootScopedChannelsJoined` | Three actual workers joined, exact purposes checked, all returned channels held through final ACK | Any original Err/panic closes Gate and the enclosing scope still joins started workers |
| Actual publication CURRENT/target/selection/FinalUse readers | `OriginalRootScopedChannelsJoined._publication_owner` | Same final ACK; not reconstructed from a digest | Retained until bundle Drop |
| Learning listener/backend, original phase record, actual scope receiver and original A object | `OriginalRootScopedJoined` | Actual scoped worker return and final ACK | Real resources retained, no serialized/rebound cap |
| Initial listener, phase control listener and original A-retirement state | `OriginalRootBusinessJoined` | Initial and scoped worker joins, followed by final ACK | Same original Gate and cleanup responsibility |
| Original Service, issuer/clock/checkpoints, registered writer proof and observers | `OriginalRootPhaseWorkersJoined._original: PreparedHostAuthoritySession`, declared after business fields | All enclosing joins and final ACK | This original service is the last field of its phase bundle to drop |
| Initial/CURRENT registration result data | `OriginalRootHostJoined._registrations` | Actual registration thread joined and final ACK | These result records are retained data; they are not substitutes for the real service/owner fields |
| Approved Root deployment files, path/inode pins and bound progress listener | `OriginalRootRetainedDeployment` | Actual material-bridge return, repeated retained-file/pidfd checks, final ACK | Original file failures remain fatal |
| Actual final progress peer and its shutdown alias | `OriginalRootRetirementPeer` | Complete exact sequence-2 response, original postchecks, then same-channel EOF-only wait with the original peer/end still valid | Remains in the same Gate registry; any join/poison/deadline/peer/byte error closes it; success never rearms the stream slot |
| Deadline watcher handle | Deployment's real scoped handle | Private stop signal only after actual joined host/material bundle, then real `join()` | Error or panic closes Gate; it is not silently discarded |
| Writer-lock File consumed by original three-right handoff | **Daemon's received descriptor/Config custody, not Root's RegisteredWriter** | Governed by the daemon's separate actual owner/worker/consumer joins and final File drop | Root ACK does not attest its release |

All table entries that say resources are held through the final ACK additionally remain held through the subsequent final-peer EOF-only wait. On the normal Root-only path, all actual worker joins precede construction of the all-workers bundle. Final peer validation and the actual ACK precede `mark_original_workers_acknowledged`. The same consuming peer method then keeps the joined bundle borrowed while it waits for the original live peer's clean EOF; any additional byte, partial frame, peer death, original deadline or other error remains failure. Only afterward does the method return and drop its still-armed close guard; the outer deployment also explicitly closes the Gate, then drops the joined resource bundle. `PreparedHostAuthoritySession` remains the final phase-owned service field. On any failure, the same real owners still perform shutdown/join/drop; no closed Gate or zero count becomes success.

The precise writer boundary is independently visible in these unchanged sources:

- `authority_host_writer.rs`, `13bd0e2313911ca9385ac31eb4281801cf97b3ad`: `RegisteredWriter` contains registration, lease verifier and proof, and no File.
- `authority_host_material_recovery.rs`, `c2afc2f93070dddfd1145b3a2ab8f219742e3b69`: `original_root_writer_descriptor` validates and opens the actual Root0600 writer descriptor under original live/Starting/material checks.
- `root_production_writer_handoff.rs`, `deb83fae10fb7799d7faf1d3514a26aaf3488222`: `send_root_production_writer_handoff(..., writer: File, ...)` consumes that actual descriptor while sending the original three rights.
- New host source `2c3d72e02c038c81152a1846aa606f1763205e46` passes the owned `registered_writer` into that unchanged sender. The Root bundle retains Service/PreparedSession and registration state afterward; it does not regain the transferred File.

## Default-path byte evidence

Nine modified production files retain their complete original file as an exact byte prefix; only new retirement methods/types follow. These include the old phase worker, five-lane serve method, learning checkpoint serve method, Model/publication/Learning session wrappers, listener implementation, typed host, and progress server.

Removing only the three-line opt-in dispatch from final `serve_deployment` yields the original 2,758-byte body exactly, SHA256 `adbe625a81af40d756c92eac6a5a14ddd6f04c7bf70ac21f09c833c899cdcd0a`. The entire original 8,627-byte progress implementation is the unchanged prefix of the successor, including its mandatory EOF error and rejection of an extra stage. Absence of the mode takes that original path.

Model and publication transport are the deliberate limited exception to full-prefix equality. Their shared inner functions now optionally retain a real retirement admission through the frame and return the actual original channel. Legacy `None` maps that returned channel to Drop; the old non-retirement phase passes an absent retirement lane and retains its original EOF error. Their original authority/effect/clock/witness checks were not removed. The exact operation packets make these additions reviewable. No claim of an entirely byte-identical shared helper is made.

The original contracts peer file is exactly reconstructed by removing only `wait_for_original_peer_eof`; original `request`, `exchange` and all other prior bytes are unchanged. That new method consumes the existing stream slot once, checks `owner.end`, reads one byte using that end, rejects any nonzero count, postchecks the live original peer on EOF, and shuts down on error. It does not parse another frame, capture another request deadline, or restore the stream. This fixes the verified ordering gap in which writing ACK2 could let Root return before the client completed its original postcheck. A client must finish all real ACK2 checks before closing its actual stream and aliases while keeping its daemon process alive; it cannot wait for Root exit first. EOF is only an ordering condition, not a claim of ACK consumption.

The four private retirement reexports and the Linux-only protocol declaration are additive. The public legacy authority API, original handoff format, UID/peer/permission checks, Root17 selector, harness, timeouts and retry policy are not changed by these packets.

## Ten new component tests and limits

The final test source is `authority_host_same_actor_q24_retirement_tests.rs`, blob `b6ee1b7393c9e96c54ed1754117a676f0f1307cf`. It is declared beneath the actual deployment module.

Four tests exercise codec/configuration data only: exact incarnation/CURRENT matching; wrong purpose/sequence/intent, unknown fields and noncanonical/oversized frames; ACK/request/intent binding; and the absent or sole allowed Root-owned mode. Within that fourth component, None must serialize to the exact old five-field object and byte sequence without a new null; explicitly disabled null is also checked. Their synthetic identity/digest data grants no authority.

Three tests consume actual scoped thread handles and actual UnixStream pairs through the same private join helper called by the production material bridge and deadline watcher. They check retained returned owner lifetime by real WouldBlock/EOF, original PermissionDenied cause with actual Gate shutdown of a blocked peer, and panic-to-error closure of the retained peer. They do not use a fake Root factory or manufacture a successful Root/C receipt.

Three additional transport components are appended to the entire unchanged original `authority_host_peer_tests.rs`, final blob `5caf2ac3fdd3941694efac25c14d7142b535b69c`. They use an actual framed request with its original client pidfd/deadline postcheck followed by closure of the retained stream, reject an extra byte or extra frame without rearming, and start an actual child that connects to a Unix listener before its real pidfd becomes readable. The last component requires PeerDenied even when that actual process exit also causes EOF. None models an actual Root deployment.

All ten are source-only, unexecuted components. They do not test the entire Root serving protocol, a real C workload, physical daemon joins, writer-lock release, or OS exit/restart qualification. No additional test is counted in the original fixed Root17 acceptance set.

## Remaining composition and qualification

The actual daemon normal C/learning/route/slot/session/circuit caps and their real shutdown/join sequence are separate work owned by the other slices. The finite wire must not be called as an automatic completion signal merely because CURRENT was registered or a third progress ACK arrived. Root-approved dynamic material writers remain the explicit deployment authority boundary; peer Prepared data alone is not Root approval.

The final CALLERS postimage is `22f4071c9458fbcdb4b3decca73458b1e74e2081`, based exactly on corrected `cec0af947a10465414faff8f4e755e023a7f892d`. It preserves the original 638 boundary IDs and adds 32 actual boundaries, for 670 declared and required IDs; 17 new protected records plus the old 440 give 457. Twenty-two existing caller sets only gain actual callers; two existing transport protection sequences adapt the literal optional-lane tuple, and the existing contracts-peer row only gains its new EOF-only function order. Every new protected row explicitly includes required and forbidden keys. Thirty reversible metadata operations include these changes. The scope includes copied original calls in the real retirement worker and the predecessor future CLI additions. Other future slices, including B and daemon callers, must be semantically unioned; this whole postimage must not overwrite another future union.

The bounded source check covers 25 actual production texts, 47 new/extended function orders and eight file-level orders with a pure V8 masked projection. The original full checker and typed helper were not run and their global type/field index was not rebuilt. Original caller markers for all 22 added edges were checked in the actual sources. Existing QA fixtures with exact caller tuples and the exact large-blob allowlist may need their independently reviewable final-union updates. This document does not assert full-source caller/checker success.

The original acceptance dimensions remain `ordinary_complete_chain=0`, `positive_adoption_chain=0`, and `no_update_or_rollback_chain=0`. Root OS exit/restart and independent-consumer qualification remain unaccepted.
