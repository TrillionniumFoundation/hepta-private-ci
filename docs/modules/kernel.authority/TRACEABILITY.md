# kernel.authority target-to-execution traceability

This table is the canonical reader entry point for distinguishing target
contracts, repository-controlled native implementation, product source
composition and external qualification. “Target-only” means the contract is
registered but no equivalent `kernel.authority` product consumer is currently
proved. A source-composed caller is still not a deployed or accepted process.

| Target / concern | Native API or owner | Current product caller | Verification / evidence | Candidate state |
| --- | --- | --- | --- | --- |
| `authority_lease` | `AuthorityLeaseRegistry` admin + `AuthorityLeaseVerifier` | `runtime.fleet` consumes the verifier at the concrete allocation issue owner boundary in `codex-rs/hepta-fleet/src/authority_port.rs`; no deployed process selected | exact-predecessor identical retry, wrong-predecessor rejection, stale-token, lock-wait expiry, prune/frontier tests; fleet exact-binding/revocation tests; B4 inventory | native owner + one concrete generic-lease source composition implemented; activation pending |
| `capability_revocation` | lease `revoke`; FinalUse signed feed V2 | `BaoFinalUseHost::apply_revocation_update`, fleet revocation coordinator and Agentd automation signed-feed refresh are source-composed boundaries | lease/control tests; signed-feed tests; B4 inventory | native implemented; deployed transport and target SLA external |
| `VerifiedUseTokenWitnessV1` | serializable non-authorizing witness emitted by FinalUse and general-lease consumer/dispatch entry APIs | `automation.taskflow` persists the exact FinalUse dispatch-entry witness in its effect-dispatch ledger before provider contact; Agentd invokes that path; fleet exposes `issue_with_witness` for owner-side evidence composition | strict round trip/unknown-field tests; immutable SQL witness row; restart and provider-response-loss recovery tests; B4 caller inventory | witness protocol source-implemented and consumed by one durable product path; external evidence acceptance pending |
| Agentd automation provider effect | `AgentdAutomationEffectHost`, `AgentdFinalUseTrustStore`, `ProviderEffectTaskFlowDriver` | named non-test Agentd host opens rotating issuer trust, authenticates a signed revocation feed, binds exact payload/scope/destination, persists durable attempt+witness and dispatches through the registered HTTP provider adapter | host process tests; single-writer handoff; restored-snapshot rejection; revocation-pending test; crash/ack-loss/no-redispatch reconciliation tests | named source composition implemented; no deployed profile, target trust qualification or activation claimed |
| `ModulePort::kernel.authority::secrets.heptabao` | `BaoFinalUseHost` public boundary + crate-private typed Bao delivery gate | registered host exists; no deployed process selected | real TLS host test covers feed expiry during provider I/O; OpenBao lane; B4 requires zero product callers of raw `BaoClient::consume_kv_v2` | source composition hardened; activation pending |
| `ModulePort::kernel.authority::auth.authbus` | no generic lease consumer; AuthBus retains its own signed admission/evidence owner | none | AuthBus qualification is separate | target-only for generic authority port |
| `ModulePort::kernel.authority::browser.servo` | Browser uses the signed FinalUse family, not a generic lease port | `hepta-agentd-browser` and `BrowserServoPort` cross the bounded local dispatch boundary | Browser authority challenge/dispatch tests and B4 caller closure | FinalUse source composition exists; registered generic port remains target-only and process still uses compatibility trust construction |
| `ModulePort::kernel.authority::channel.matrix` | no generic lease consumer | none | Matrix owner tests are separate | target-only |
| `ModulePort::kernel.authority::inference.control` | no generic lease consumer; durable inference control has its own journal/fences | none | inference-control tests are separate | target-only |
| `ModulePort::kernel.authority::inference.worker` | signed FinalUse authorizer exists, not a generic lease consumer | inference worker host claims exact signed grants before App Server effect entry | worker-host tests/B4 | signed FinalUse source integration exists; generic port target-only and target host qualification external |
| `ModulePort::kernel.authority::memory.federation` | none; memory production writer has its own external verifier contract | none | memory/Agentd qualification is separate | target-only |
| `ModulePort::kernel.authority::runtime.codex` | exact-frontier `VerifiedUseToken::enter` | runtime Codex/inference App Server path consumes an opaque entered token before first effectful await | exact-head entry tests and caller inventory | signed FinalUse source integration exists; generic port target-only |
| `ModulePort::kernel.authority::runtime.fleet` | `FleetAuthorityPort::issue` consumes `AuthorityLeaseVerifier`; `FleetRevocationCoordinator` composes signed feed + enrolled-node convergence | `authority_port.rs` and `revocation_control.rs` are non-test source-composed callers; no deployed process selected | exact binding drift + post-revocation denial; coordinator catch-up/quarantine/stale-feed tests; B4 caller closure | generic lease + revocation control-plane source composition implemented; wire fanout and activation external |
| `ModulePort::kernel.authority::runtime.supervisor` | supervisor H7/H8/H9 signed production grant remains a separate protocol | real supervisor caller exists for that separate verifier, not the generic lease port | supervisor tests/B4 | target-only for generic port; existing supervisor authority not re-labelled |
| trusted time | `AuthorityClock` bound into FinalUse and general lease owners | Agentd automation supplies `AgentdFinalUseTrustStore`, which persists a monotonic floor outside Agent home; other hosts remain host-supplied | clock rollback/reopen tests + production-evidence v2 admission | one concrete source host exists; attestation and target clock uncertainty qualification external |
| anti-rollback | `AuthorityFrontierStore` CAS, `FinalUseFrontier`, `AuthorityLeaseFrontier` | Agentd automation supplies an owner-locked external FinalUse CAS store outside Agent home | exact-CAS conflict, owner handoff, missing-frontier and restored-local-snapshot tests; content-addressed external receipt admission | one concrete source backend exists; selected deployment rollback independence external |
| revocation progress | signed feed apply + `revocation_pending` admission fence | Agentd automation refreshes the signed feed before dispatch; guarded TaskFlow effects hold the active-effect fence | active effect causes `DispatchInProgress`; new claims fail `RevocationPending`; exact update retry commits after drain | repository-controlled no-new-admission rule implemented; pending bit is process-local and restart re-reads the signed feed |
| revocation freshness / fleet convergence | signed FinalUse feed V2 + local-apply receipt + exact node ack + convergence verifier | Bao source host, Agentd automation host and fleet source control plane; external wire transport supplies fleet envelopes/acks | in-flight expiry; wrong receipt; stale/future ack; forged distributor; fleet catch-up/quarantine/stale tests | authenticated repository chain implemented; deployed wire latency evidence external |
| key rotation | bounded epoch-window issuer/approval/feed key rings; issuer trust-set digest pinned in FinalUse store V3 | Agentd automation host loads issuer and distributor rings; other hosts have their own composition state | overlap/retirement tests; production bundle requires custody, staged rotation and compromise receipts for all three roles | protocol/source composition implemented; HSM/KMS ceremony external |
| capacity / GC | bounded stores; lease prune/epoch rollover; FinalUse append-only local claim journal plus full external-frontier digest | authority owner/selected host | source bounds and capacity tests; production evidence v2 requires complete 5-by-11 numerical matrix, structured fault results and reserve alert | bounded behavior implemented; target-host performance evidence external |
| no-bypass proof | `CALLERS.toml` + `KERNEL_AUTHORITY_BOUNDARIES.json` | repository scanners | independent B4 public-surface classification plus whole-repository caller proof | repository-controlled |
| activation / release | none | none | implementation map + exact-head/merge receipts + external acceptance | false until separate gates pass |

## Reading rule

A row is production-composed only when it names a non-test product caller and
that exact candidate has current execution evidence. Native types, examples,
fixtures, documentation, B4 “no caller” results or successful unit tests do not
upgrade source composition into deployed product authority. The Agentd trust
store closes one repository-controlled host composition; it does not
self-attest the clock, storage or backup domain on a selected target.

The general V1 lease trust decision is in
[ADR-0001-LEASE-TRUST-MODEL.md](ADR-0001-LEASE-TRUST-MODEL.md). Consumer-entry
ordering is in [LINEARIZATION.md](LINEARIZATION.md). Current non-claims remain
in the lane-A
[CURRENT_IMPLEMENTATION.md](../../lane-a-foundation/kernel.authority/CURRENT_IMPLEMENTATION.md).

Recovery note: the normal Agentd host uses frontier-verified key-ring recovery
and then authenticates/applies the current feed before admission. Exact open
retains its old head-equality requirement. These are distinct classified
entrypoints, neither of which establishes target-host trust qualification.
