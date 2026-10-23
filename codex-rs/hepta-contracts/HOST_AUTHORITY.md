# Local host authority backends

`RootAuthorityDirectory` and `HostAuthorityFrontierStore<F>` implement the
existing `AuthorityFrontierStore` contract for a root-owned host broker. They
do not create an authorization policy, signing key, writer, or business outbox.
The original FinalUse and authority-lease owners remain responsible for
signature, epoch, revocation, nonce and effect-entry decisions.

## Protection boundary

The broker's directory must be outside the Agent's writable state. Opening it
requires effective UID 0, an absolute path, root-owned ancestors without group
or other write permission, and a mode-0700 final directory. Each component is
opened relative to a retained descriptor without following symlinks. The
backend retains the directory descriptor.

This protects a frontier from an unprivileged writer restoring or deleting its
own local authority directory. It assumes a trusted operating system and root
administrator. It does **not** claim TPM protection, remote attestation, or
resistance to rollback of the whole host and its protected directory.

Agent processes must not directly receive this directory handle. A separately
authenticated private broker channel supplies their `AuthorityFrontierStore`
callback. The backend alone does not establish that channel or peer identity.

## Persistence and failures

Each authority owner has one bounded JSON frontier record, addressed by a
SHA-256 hash of its owner ID. Records are limited to 16 KiB. Mode-0600 regular
files must have exactly one link and the broker's UID. Registration is explicit
and only succeeds when the owner has no existing record. Opening never creates
or repairs state. Different original owner domains need different owner IDs.

CAS takes a nonblocking process lock, reads and compares the complete expected
value, writes and fsyncs a private temporary file, atomically renames it, then
fsyncs the retained directory. Lock identity is rechecked after acquisition.
A stale incomplete temporary file can be replaced under that lock; an unsafe
file or symlink is refused before truncation. A killed process releases the OS
lock. Uncertain errors remain errors; callers must use the original owner's
fencing/reopen protocol, rather than assume that a failed call did not commit.

FinalUse already advances its external frontier before appending its local
nonce journal. If the latter fails, an ahead-of-local external frontier rejects
reopen. The host must retain that mismatch for authorized recovery; it must not
reset the protected frontier from the local directory.

## Verification

`authority_host_store_tests.rs` exercises actual filesystem CAS/reopen, two
concurrent processes with one winner, controlled SIGKILL after durable commit,
stale temporary files, unsafe entries, and original FinalUse signature/nonce/
revocation checks followed by rejection of a restored local snapshot.
The tests' ordinary-UID directory helper is private to their test module. It
does not relax the production root-directory constructor. Subprocess entry
tests are marked ignored and are launched explicitly by their parent cases.

This backend is one deployment prerequisite. A real clock, issuer, private
endpoint, runtime loader and authenticated cognitive current-cut protocol are
separate requirements and are not implied by these filesystem tests.
