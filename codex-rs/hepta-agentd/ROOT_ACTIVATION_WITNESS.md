# Original Root activation preparation

An original signed writer proof identifies the Agent, Supervisor spawn, owner
epoch, local lease generation and complete authority lease. Before its physical
checkpoint is installed, the checkpoint still identifies the preceding
publisher. Neither the unsigned PID nor the signed writer proof alone records
the new publisher's actual boot and start time. A cold opener must not infer
that missing lifetime from a later process at the same PID.

The original checkpoint owner now prepares one immutable process observation
before publishing the candidate lease or requesting its canonical signature.
Preparation requires the complete actual preceding checkpoint, its independent
retirement object, its retained physical material, and the new publisher's
actual captured pidfd. It holds the original checkpoint publication lock while
checking the actual complete head and saving the observation through the
existing Root directory's lock, file sync, rename, directory sync and readback.
It does not create or modify the checkpoint.

## Binding and selection

The original authority lease's `binding.payload_sha256` commits to a domain,
the complete candidate registration with that output field zeroed, the whole
original predecessor token, its exact physical cut digest, and the actual Root
and publisher lifetimes. The existing scope, operation class, destination,
finite times and all other candidate fields are retained. Original registry,
writer proof, RootSession and strict signature checks continue to validate the
complete exact authority lease. Ordinary writer rotation never required an
old payload preimage or equal payload hash across a new lease.

The observation ID is `checkpoint-activation-v1.<SHA256(candidate JSON)>`.
It lives in the original checkpoint Root directory using the existing bounded
`observation-v1-<SHA256(id)>.json` format. The complete stored record remains
limited to 16 KiB, owner Root, mode 0600, one link. Its payload contains exactly
`schema_version`, `previous_token`, `material_cut_sha256`, `root`, `peer`, and
`candidate`. Equal durable preparation is idempotent; a different record at the
same identity is refused. An unpublished candidate supplies no authority.

Cold selection comes only from the original issuer's independently verified
currently retained canonical proof. The opener derives the observation ID from
that exact candidate and checks both its full equality and the signed payload
commitment. A missing or malformed record, different boot/peer/candidate,
changed complete predecessor token, changed physical material, or a candidate
that was saved but never became canonical cannot provide retirement evidence.
The issuer state and actual Root are checked again after the original locked
physical-cut observation. No scan, latest-file heuristic or caller-provided
PID chooses the record.

## Retirement boundaries

Within the same actual boot, the original pidfd/start-time retirement observer
is still mandatory; a live publisher is refused. Across an actual boot change,
the concrete original HostAuthorityClock must first durably admit the actual
new Root boot under its retained highwater. Only then may the original owner
construct private `PriorBootActivation` evidence from this canonical-bound
prepared record.

That new evidence is accepted only for replacing the exact unactivated proof
under `with_unactivated_writer_cut_for_root`. It is explicitly rejected by
clean-Current adoption, physical-head adoption and native namespace policy
administration. The actual predecessor head still needs its own independent
retirement and physical material. Registry lease retirement, original issuer
sequence/CAS, exact unused local generation, actual live successor pidfd and
the original final clock checks remain separate gates.

Once the checkpoint actually contains the candidate generation, this witness
cannot reclassify it as unused. The opener uses the actual installed head and
the normal strict next-generation physical recovery path.

## Verification scope

The sibling Root tests use the original canonical fixture and real UID60001
children. They cover file/directory durability before lease/signature
publication, an unsigned candidate refusal, a live publisher refusal, actual
SIGKILL/reap after signature, reopening the original dead publisher, a further
original same-generation replacement, missing/truncated data, changed Root or
peer identities (including changing both boots together), candidate/full-token
and physical-cut binding changes, and refusal to reuse an actually installed
generation. They do not simulate a positive second kernel boot.

Native composition saves these preparations before successor lease/signature
publication and cold-opens only the canonical candidate. It also calls the
original Registry's explicit Root-only completion of a prepared state before
the normal pinned runtime factory; ordinary runtime open keeps its strict
anti-rollback behavior. A real two-VM same-disk case remains necessary to
qualify the cross-boot branch. Initial genesis without a protected predecessor
is deliberately not admitted by this API and requires its separate original
installation preparation.
