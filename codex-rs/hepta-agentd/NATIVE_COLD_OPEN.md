# Opening the original native installation after a boot change

Fresh installation writes `protected/installation.json` once, as a Root-owned
0600 regular file with file and parent-directory synchronization. It retains
the independently installed issuer public-key pin, original service paths,
required-bind device/inode and fixed consumer registrations. The record is
installation configuration, not a writer or effect ledger. A later startup
never obtains its trust pin from the issuer it is trying to authenticate.

The mounted state directory has two paths. Absence permits the original
explicit fresh setup. Presence requires exact owner/mode checks and the
original open-only Fleet, Root clock, lease registry and issuer. Missing or
partial installation metadata is an error. Existing authority, local stores
and protected frontiers are never reset, repaired or initialized as genesis.
The original required-bind device/inode check remains exact across boots.

The two original FinalUse local stores now live in the Host's private
`/state/hepta-native/consumer-local/{device,notes}` directories on the same
physical state disk. Root bind-mounts that exact held directory at the existing
`/run/hepta-native/owner/consumer-local` path, verifies its device/inode, and
keeps the original sealed path and Root ancestor validation unchanged. Their
complete nonce state must survive a reboot with
the protected Root frontiers. Keeping only the frontier hashes while losing
the original local nonce state would not be recoverable. Cold opening requires
these directories to exist; the original FinalUse owner subsequently checks
their contents against the existing original Root frontier.

## Original owner sequence

Root reads the actual canonical signed writer metadata and the complete
protected checkpoint through their administration-only reads. It reconstructs
the original writer binding with `VerifiedRootWriterProof` and requires full
equality with the retained checkpoint binding. It locates the exact retained
physical last-Current image, verifies that existing image, and then obtains
the separate original prior-boot retirement proof. Reading a mutable current
SQLite database cannot supply this proof or replace missing material.

The new actual proc boot UUID must agree byte-for-byte with the original
kernel bootstrap/launcher boot. Root observes the existing two protected
FinalUse frontiers and canonical CPU policies. Before admitting any new Root
session or Host, it selects all not-yet-retired original leases of this Agent,
revokes each through the original revision-checked registry, and verifies the
entire active selection is empty. Expired/revoked historical rows do not
consume the active-query bound. The actual old local-writer expiry is still
waited out; boot change does not shorten or alter it.

The existing Supervisor independently rejects an old persisted ProcessIdentity
whose boot/start time differs, removes that old process lease through its own
recovery path, and allocates the next real spawn generation. New Root and
writer lease IDs include the actual current boot and this original spawn,
so retrying an unactivated local generation does not reuse an old lease ID.
Already-revoked records must match the complete original issued lease plus
its actual revocation; absence alone is never retirement evidence. The
original canonical registry pair boundary remains the final authority gate.

Normal physical adoption still advances the original local generation,
publisher epoch and checkpoint counter strictly by one. The new-boot initial
Manager's namespace policy uses an actual initial kernel launch receipt and
the independently verified prior-boot proof under the original exact two-slot
policy CAS. It does not invent a previous-boot watchdog receipt or resolve an
old K/D. Old-boot pending effects remain Indeterminate and remain drain
blockers; they cannot be retried through the fresh namespace.

## Qualification and remaining integration

`root_native_retirement_preserves_original_issued_record_and_revocation` uses
the actual Root clock/registry and real durable files. It checks one original
revocation, unchanged repeat observation under another administrative reason,
rejection of a changed issued binding, and continued rejection by the runtime
verifier. It supplies no kernel boot evidence.

Positive cold opening requires the separate same-disk, two-kernel-boot native
campaign described in `ROOT_BOOT_RECOVERY.md`. In particular, an old pending
operation must remain unresolved after the adapter's real boot-mismatch
refusal, with no old Install or Query ioctl. Current cold opening rejects a
canonical proof that advanced beyond the actual checkpoint; that interrupted
activation must be reconciled through the separately tested original reentry
API before it can be accepted. These are explicit native integration gates,
not success inferred from the host test or source review.
