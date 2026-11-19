# trillionnium-os-desktop / Organ integration audit

Observed on 2026-10-21 UTC. Complete metadata pagination found **196 branches**
and **215 pull requests**, including **29 open** and **130 merged**. PR numbers
are not a count: the latest observed number is #225. Page sizes and empty
terminal pages are recorded in [pagination.json](pagination.json). This is not
a complete semantic or native-device audit of all 215 PRs.

## Later exact-head refresh

At **2026-10-21 01:35:51 UTC**, both parallel kernel owners advanced again:

- #224: `49e5582db15493eed60d62fb16b4c85fc7408307`
- #225: `9476f50e9c18745369300b3f2b7d5cf2ad09a713`

Each new head has six queued checks at capture. The six successful checks in
the initial table below belong to older heads and are not transferred to these
new commits. Their new native and artifact qualification remains open; no
source-semantic claim is inferred merely from advancing the head. Full current
IDs and timestamps are in [../ci-live-final.json](../ci-live-final.json).

A separate read-only [broker finding](broker-review/README.md) records unbounded
session admission in the pinned #210/#218 implementation. The diagnostic source
is explicitly uncompiled/unexecuted; current callers are limited to the reviewed
crate tests, so no deployed remote-denial-of-service claim is made.

## Initial integration-owner observations

| Owner | Exact head | Observed result and boundary |
| --- | --- | --- |
| Main | `e524064d985ad2e1ade2099bc3d701c29484b3eb` | Includes the merged publication-maintenance work; this alone does not qualify Organ device effects |
| [#210 — Organ broker](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/pull/210) | `987d0d992ad5faa522676759a508d2bbdccdf3fa` | Draft; previously reported exact-source checks are successful, but the broker deliberately remains before A05/A07 integration |
| [#224 — kernel integration](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/pull/224) | `a8d2db5fe0fbbd53bd50ec7204aa0aad213b0414` | Draft; six checks successful and exact-kernel test in progress at capture |
| [#225 — inode/storage convergence](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/pull/225) | `84e2c9fb45ff88f4352853f5ed4462dd56c6a01d` | New parallel owner; six checks successful and exact-kernel test in progress at capture |

#225 reports a three-parent convergence and current G1-c/G1-d artifact review.
The live API confirms those jobs' success, but this audit did not repeat that
owner's full kernel artifact verification. Its A06/core/OSTD/SMP/disk result
must be checked independently at the exact combined head. Neither #224 nor
#225 was overwritten, closed or merged by this work.

## What the current broker actually provides

The pinned [implementation](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/blob/987d0d992ad5faa522676759a508d2bbdccdf3fa/ui/broker/src/lib.rs)
has Git blob `6b1da02bc04dc09a96d86eb3afa9ca999ef1f80c`; its
[boundary document](https://github.com/TrillionniumFoundation/trillionnium-os-desktop/blob/987d0d992ad5faa522676759a508d2bbdccdf3fa/docs/ORGAN_BROKER.md)
has blob `29078761fa879846b04733db2f17c1dc1738bca3`.

| Area | Verified source behavior | Remaining integration requirement |
| --- | --- | --- |
| UI protocol | Versioned, bounded fields; no raw pointers, signer or device handles | Validate version and resource limits at each transport adapter |
| Peer authentication | Linux kernel same-UID credentials; handles are bound to one Broker instance | Same-UID application identity and A05 grants; other platforms need native peer evidence |
| Capabilities | Observe, OfflineDraft and Reconcile only | SubmitEffect and CancelEffect remain denied until original owner authority exists |
| Operation identity | Durable intent K stays separate from boot-local delivery D | Original durable owner ledger, restart reconciliation and K-to-D binding |
| Generations | Authority/body/resource/bridge/owner fences are distinct | Bind those fences to signed admission and actual Final-use checks |
| Receipts | Missing owner evidence stays unknown; receipt shape does not authenticate a signer | Verify original owner signatures and effect binding before a terminal state is accepted |
| Notifications | Bounded queue; dropped prefixes require pull/reconcile | Test disconnect, replay and recovery against the real owner and device |
| Offline drafts | Explicitly local-only | A later online submission requires a new validated authority decision |

This is a usable boundary for observer/draft/reconciliation development. It is
not evidence of authorized desktop or mobile device control. The broker is
still a draft outside main, and successful kernel profile tests do not supply
application identity, production Hepta durability, or physical device tests.

## Next concrete integration sequence

1. Preserve #210's default-deny API while the A05 owner supplies authenticated
   application/process identity, capability scope and revocation epochs.
2. Add an internal original-owner adapter that verifies signed admission and
   Final-use immediately before an effect. The UI must never write the owner
   ledger or accept a client-supplied `confirmed_by_owner` boolean as authority.
3. Bind K, D, all generation fences and payload digest to durable receipts;
   exercise restart, cancellation, lost notification and duplicate delivery
   against the actual owner. Unknown delivery outcome must stay unknown.
4. Qualify each OS/device adapter separately. Linux UDS credentials do not
   certify Windows named pipes, macOS peer identity, mobile pairing, or a
   physical device. Pairing, scope confirmation, revocation and disconnect
   behavior need their own authenticated evidence.
5. Measure owner-to-device latency, memory and notification/recovery cost with
   an explicit workload. No performance or cross-device parity claim is made
   from the current static source or kernel-only profile.

No device command, production grant or topology change was issued. Remaining
application identity, Final-use, durable effect/recovery and device evidence
are open blockers, not prerequisites silently treated as satisfied.

## 发布前补充：01:54:37 UTC

#224的49e5582d和#225的9476f50e在本次有界首尾读取中均保持稳定。
两个当前head各有6项success、1项exact-kernel-ktest仍in_progress，job分别为
118984639491、118985116581。完整记录见
[ci-live-publication.json](../ci-live-publication.json)。该结果未证明完整内核、设备或effect资格。
