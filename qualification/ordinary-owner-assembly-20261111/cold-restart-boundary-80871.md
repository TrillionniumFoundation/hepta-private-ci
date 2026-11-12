# Cold-restart boundary — fixed 80871

**Static only:** commit `80871cc70dbde29e61aa655b18957bfcc36056d3`, tree `dd0234485d40f9109e46394c94d505952a07cb08`. Selected sources and commit were directly read. No execution, edits or ref changes; no new Root17 qualification.

## 1. What the two Root17 parents actually do

The parents `root_initial_publication_uses_original_consumer_and_readonly_recovery` and `root_broker_late_enrolls_publishes_and_recovers_original_current` retain the **same Root process and same fixture child across phases**: one UID60001 spawn per fixture, `run_phase` reopens Prepared with the same registration/pidfd, and the child loops through phases before final release/join. Initial's two lost-ACK settings are independent fixtures. The earlier cached “different child per phase” description was incorrect. [I] [P]

They check original CURRENT/claim/journal preservation, no second nonce and retired-session/corruption/revocation rejection. Initial does not execute ordinary A; Publication uses synthetic component learning observations. Neither establishes daemon+Root OS replacement, machine reboot, ordinary A→B→C or independent-controller C. [I] [P]

## 2. Durable recovery that really exists

| Existing interface | What can be recovered; required originals |
|---|---|
| `NeuronGenerationCurrentOwnerV1::open`, `recover_operation`, and initial readback | Reopen protected CURRENT and exact operation/intent; no new claim/frontier or live connection. [G] |
| `recover_agentd_generation_initial_v1` | Requires actual CURRENT/authorities/selection and original target file+witness/config. Revalidates and opens the guarded journal; Prepared-only rejects without redispatch. [GI] |
| `PreparedHostAuthoritySession::open_with_physical_material` / `observe_physical_current` | Verify original material/Current and live registration. Observation grants nothing; `resume_physical_material_handoff` only finishes existing custody release. [M] |
| `recover_with_physical_material` | **Mutating recovery/adoption:** verifies protected predecessor, independent image, actual retirement, successor and lease windows, then installs/adopts. No caller-selected replacement Current/image. [M] [R] |
| `CellQ24PreparedLearningV1::recover` | Requires actual ledger/task capabilities and frozen Dataset; compares exact initial/scope. No refreeze, renewal or retained-A capability minted from receipts. [D] |

Adoption requires actual old-peer retirement, a different live publisher, same boot/UID/owner, advanced epochs/lease generation and changed grant/fencing bindings. Expiry alone is insufficient. Supervisor uses actual Exited→lease removal→Stopped→Starting/spawn. Same-boot replacement does not cover reboot. [R] [A] [S]

## 3. Existing production callers, accurately bounded

A real caller exists: `native_g2_entry::root::run → recovery::run` observes actual Manager exit, joins service, waits for lease expiry, performs Supervisor/writer rotation and calls physical recovery. The successor's `Command::Reconcile` reads `retained_hos2_terminal` and `observe_retained_native_delivery`, comparing original request/terminal/event/observation before acknowledgement. **Root remains alive.** Its original native control/image/PID-1 capabilities are prerequisites; this is HOS2 composition, not Q24 cold-restart evidence. [N]

`--root-production-entry late-writer` now has a real `main → Startup` branch: actual three rights/five lanes, exact Starting/identity and writer/live checks remain required. The old “no product caller” claim is superseded. Root's default binary still lacks paired physical-recovery/three-rights startup. Public factories are available to authorized hosts; full `Launch::run` additionally needs actual Primary/app-server inputs. Five-lane fixtures do not prove that deployment. [L] [RC]

## 4. What bytes cannot restore, and the exact remaining gap

- **Live authority:** original pidfd/PID/start/boot, writer proof/lease, consumers and feed remain required. Root session Drop fences cache and retires worker; bytes cannot revive these or refresh deadlines. New Root requires a newly legitimate connection. [LS]
- **Original A:** retained source holds the actual producer/Prepared, original Automation inode/trace and ledger. Capture needs those capabilities; no historical-data-to-new-incarnation constructor exists. `circuit_task_source_codec.rs` binds full identity/spawn/resources and TaskFlowFence. Dataset recovery is not a substitute. [D] [T]
- **Learning/phase:** profile checks exact identity/writer-proof digests. Material recovery leaves learning/publication/Initial absent; it does not rebind frozen scope or restore consumed offers/slots. Proposed same-session phase installation is not a cold-recovery API. [M] [F]

**Remaining contract:** no reviewed API authorizes historical A/frozen learning custody to a new daemon incarnation after both processes die. Lower-level state recovery and the CLI do not close it. These tests also lack actual two-process replacement qualification. No new protocol is proposed. **Ordinary complete / positive adoption / ordinary NoUpdateRollback remain 0 / 0 / 0**; same-principal new-run C is not independent adoption.

## Pinned source references

Links pin the reviewed commit; previous reports served only as navigation.

[I]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/authority_host_generation_initial_fixture_tests.rs
[P]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/authority_host_generation_publication_root_fixture_tests.rs
[G]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/neuron_generation_current.rs
[GI]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/neuron_generation_initial.rs
[M]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/authority_host_session_material.rs
[R]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/authority_host_checkpoint_material_recovery.rs
[A]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/authority_host_checkpoint_adoption.rs
[S]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-supervisor/src/recovery.rs
[D]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/cell_q24_prepared_learning.rs
[N]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/native_g2_entry/recovery.rs
[L]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/production_launcher.rs
[RC]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/bin/hepta-authority-host.rs
[LS]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/root_authority_session.rs
[T]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/cell_q24_retained_learning_source.rs
[F]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/80871cc70dbde29e61aa655b18957bfcc36056d3/codex-rs/hepta-agentd/src/authority_host_learning_profile.rs
