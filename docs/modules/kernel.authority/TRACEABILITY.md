# kernel.authority target-to-execution traceability

This table is the canonical reader entry point for distinguishing target
contracts, repository-controlled native implementation, product composition and
external qualification. “Target-only” means the contract is registered but no
equivalent kernel.authority product consumer is currently proved.

| Target / concern | Native API or owner | Current product caller | Verification / evidence | Candidate state |
| --- | --- | --- | --- | --- |
| `authority_lease` | `AuthorityLeaseRegistry` admin + `AuthorityLeaseVerifier` | none selected | `authority_lease.rs` unit tests; B4 inventory | native owner implemented; composition pending |
| `capability_revocation` | lease `revoke`; FinalUse signed feed V2 | `BaoFinalUseHost::apply_revocation_update` is a source-composed host boundary, not a selected process | lease/control tests; B4 inventory | native implemented; fleet transport external |
| `VerifiedUseTokenWitnessV1` | opaque `VerifiedUseToken` and `LeaseVerifiedUseToken`; `deliver_final_use` / verifier final check | Bao adapter uses FinalUse path | FinalUse tests; Bao TLS/host tests | executable native analogue; no serialized bearer witness |
| `ModulePort::kernel.authority::secrets.heptabao` | `BaoFinalUseHost` + `BaoClient` | registered host exists; no deployed process selected | Bao host tests, OpenBao compatibility lane, B4 | source composition implemented; activation pending |
| `ModulePort::kernel.authority::auth.authbus` | no generic lease consumer; AuthBus retains its own signed admission/evidence owner | none | AuthBus qualification is separate | target-only for generic authority port |
| `ModulePort::kernel.authority::browser.servo` | none | none | browser authority-free proposal tests are separate | target-only |
| `ModulePort::kernel.authority::channel.matrix` | none | none | Matrix owner tests are separate | target-only |
| `ModulePort::kernel.authority::inference.control` | no generic lease consumer; durable inference control has its own journal/fences | none | inference-control tests are separate | target-only |
| `ModulePort::kernel.authority::inference.worker` | none | none | worker-host tests are separate | target-only |
| `ModulePort::kernel.authority::memory.federation` | none; memory production writer has its own external verifier contract | none | memory/agentd qualification is separate | target-only |
| `ModulePort::kernel.authority::runtime.codex` | none | none | Codex adapter tests are separate | target-only |
| `ModulePort::kernel.authority::runtime.fleet` | no generic lease consumer; fleet lease ledger remains a separate in-memory component | none | fleet tests are separate | target-only |
| `ModulePort::kernel.authority::runtime.supervisor` | supervisor H7/H8/H9 signed production grant remains a separate protocol | real supervisor caller exists for that separate verifier, not the generic lease port | supervisor tests/B4 | target-only for generic port; existing supervisor authority not re-labelled |
| trusted time | `AuthorityClock` bound into FinalUse and general lease owners | host-supplied implementation required | injected-clock tests | interface enforced; attested production source external |
| anti-rollback | `AuthorityFrontierStore` CAS, `FinalUseFrontier`, `AuthorityLeaseFrontier` | host-supplied implementation required | restored-snapshot tests | protocol enforced; external durable backend external |
| revocation freshness / convergence | signed FinalUse feed V2 + Bao freshness gate + node-signed `FinalUseRevocationAck` convergence verifier | Bao source host; external fanout supplies envelopes/acks | control/host tests | fail-closed partition/catch-up and cryptographic missing-node proof implemented; transport/latency SLA external |
| key rotation | bounded epoch-window `FinalUseIssuerTrustKey` ring for grants plus `FinalUseTrustKey` rings for approval/feed; issuer trust-set digest pinned in FinalUse store V2 | host configuration | overlap/retirement tests | protocol implemented; HSM/KMS ceremony external |
| capacity / GC | bounded stores; lease `prune_expired_leases`; explicit epoch rollover | authority owner | capacity/prune tests | lease online GC implemented; FinalUse nonce history still epoch-bounded |
| no-bypass proof | `CALLERS.toml` + `KERNEL_AUTHORITY_BOUNDARIES.json` | repository scanner | B4 closed-world test | repository-controlled |
| activation / release | none | none | implementation map / external acceptance | false until separate gates pass |

## Reading rule

A row is production-composed only when it names a non-test product caller and
that exact candidate has current execution evidence. Native types, examples,
fixtures, documentation, B4 “no caller” results, or successful unit tests do not
upgrade a target-only row into product authority.

The general V1 lease trust decision is in
[ADR-0001-LEASE-TRUST-MODEL.md](ADR-0001-LEASE-TRUST-MODEL.md). Consumer-entry
ordering is in [LINEARIZATION.md](LINEARIZATION.md). Current non-claims remain
in the lane-A
[CURRENT_IMPLEMENTATION.md](../../lane-a-foundation/kernel.authority/CURRENT_IMPLEMENTATION.md).
