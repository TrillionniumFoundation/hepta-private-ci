# Root recovery after a partially activated writer

This module adds trusted administration APIs for the original canonical writer
and checkpoint owners. They are private to Agentd and are not peer commands.
They do not start a Host, install a physical database, authorize a CPU request,
or bypass the original Supervisor. The native entry must reconcile these
boundaries before it can claim recovery from an interrupted activation.

## Decide from the original durable state

| Durable state after the failed launch | Permitted next action |
| --- | --- |
| Canonical writer proof and checkpoint both still name the predecessor | Retire the failed actual process and use the existing rotation path. |
| Canonical proof names generation N+1, while the complete checkpoint still names N | Retire the failed original authority lease and actual process. Replace only this unactivated authorization for another actual spawn, retaining local generation N+1. |
| The complete checkpoint already names N+1 | Observe that exact retired publisher's durable full head and independently retained physical last-Current image. Use this actual N+1 receipt as the predecessor for the existing strict N+2 adoption. |

A timeout or an I/O error does not select one of these rows. Root reads the
actual protected stores. It must preserve the original signed authorization,
whole checkpoint head, token and physical image until their owners determine
which transition committed. A failed one-attempt material installation remains
failed; opening the same runtime registration does not clear that fence.

## Unactivated authorization replacement

`DeploymentFinalUseIssuer::replace_unactivated_writer_authorization` requires
the original protected issuer, its retained registry verifier, a valid signed
failed proof, the actual retired predecessor and failed publisher, a held live
successor, and a verified original physical image. The failed lease must be
retired by the original registry. A dead process alone is insufficient.

The new registration has a different authority-lease ID, greater real spawn
generation and owner epoch, the same local lease ID and unactivated local
generation, and the same authority epoch and scope. It uses the existing key,
issuer sequence reservation, proof retention and CAS. An exact retained
replacement reconciles a lost response without spending another sequence.
Any other retained proof is rejected. Ordinary writer rotation still requires
local generation +1.

The original lock order is registry boundary, checkpoint publication lock,
then issuer request lock. The checkpoint owner compares the entire retained
head and token, verifies both retired lifetimes and the held physical image,
and keeps its publication lock through the canonical issuer operation. A
second durable read and repeated material checks follow the operation. No
callback re-enters the held registry or checkpoint owner. Any error can follow
a durable proof or sequence change and must be reconciled before another
activation attempt.

## Read the head of an actually retired publisher

`HostCognitiveCheckpoint::read_retired_head_for_root` is an observation API.
It requires actual Root, the exact registration, kernel-observed same-boot
retirement, and independently verified physical material matching the actual
head's last-Current cut. It reads under the original publication lock and
returns the original full receipt. Dirty, Publishing and Fenced phases remain
unchanged. This does not revive an expired lease or reopen a closed publisher.
The existing physical-adoption method alone can consume that receipt and
advance the original counter, publisher epoch and local generation by one.

## Qualification

The ordinary contracts tests exercise the real filesystem publication lock,
failed directory sync after a real rename, complete durable readback, and
post-callback corruption. The four Linux Root tests use an explicitly isolated
`HEPTA_CHECKPOINT_TEST_ROOT`, real original registry/clock/key owners, an
original SQLite image, and actual UID 60001 processes with retained pidfds:

- `root_unactivated_writer_replacement_retains_original_generation_and_exact_lost_reply`
- `root_unactivated_replacement_rejects_an_actually_committed_checkpoint`
- `root_unactivated_replacement_rejects_wrong_proof_generation_and_changed_physical_image`
- `root_real_death_after_checkpoint_cas_recovers_actual_head_without_skipping_generation`

The last test delegates every time value to the actual `HostAuthorityClock`.
At the existing post-CAS clock call it sends a real SIGKILL through a held
pidfd, observes actual death, and leaves the committed checkpoint intact. It
then reaps the child and uses the original strict adoption for the next live
publisher. This is an owner failure-boundary test, not a power-loss or native
kernel qualification. Fixture leases are issued once for 90 seconds to allow
isolated host preparation; production writer leases remain 20 seconds.

Use `just fmt`, the scoped contracts tests, and `just test` for these four
explicit ignored Root qualifications with retries disabled. Preserve failed
attempts and source hashes. The API tests and native integration are distinct
acceptance gates; neither is complete merely because this module exists.

## Cross-boot boundary

These APIs deliberately require the original same-boot retirement evidence.
A different boot needs separate Root evidence bound to the previously
protected full head and the new actual kernel boot, followed by original
authority retirement and physical-cut admission. Removing a same-boot check
cannot supply that evidence. A retained old-boot unresolved HOS2 operation
must remain unresolved and must never be re-dispatched under a new boot.
Positive cross-boot adoption and testing on the same physical state disk are
separate unfinished integration work.
