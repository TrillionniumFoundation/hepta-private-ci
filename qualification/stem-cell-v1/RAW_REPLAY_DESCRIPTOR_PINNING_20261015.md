# Group original evidence: read-once source-byte integrity

Date: 2026-10-15. Research only, **DRAFT / SHADOW / DENY_ALL**.

Frozen source parent: PR #2375 at
`330e7d6f1ee525570c407b06c04271dc6f234f1e`.

## Corrected read-side integrity risk

The original `_regular_file(path)` first checked whether a path was a
regular non-symlink and then read via a *fresh* `Path.read_bytes()` lookup.
A concurrent replacement of that path between these operations could mean
the checked filesystem object differs from the object whose bytes were hashed.
A hash cannot fix a mismatched read identity.

The new research-only intake:

- Demands POSIX `O_NOFOLLOW` and opens a single descriptor with `O_RDONLY`
  and `O_CLOEXEC` / `O_NONBLOCK` when available.
- Uses `fstat` on that descriptor, only accepting a bounded regular file,
  excluding symlinks, FIFOs and devices.
- Reads at most the fstat-attested byte length plus one byte using that
  **same descriptor**, then rechecks device/inode/size and modification/change
  timestamps. Any observed concurrent mutation or short/oversize read fails.
- Closes the descriptor on every success or failure path.
- Preserves all prior original six-block artifact inventories, model replay,
  independent public-label rechecks, cost accounting and `DENY_ALL` posture.

It is a *read-side* race-hardening gate, not a cryptographic proof of the
original producer, not an append-only signed witness, and does not prevent
malicious concurrent mutation with indistinguishable timestamps or attacks on
untrusted ancestor directories. A fully independent original owner signature
and immutable archive store remain separate scientific/production requirements.

## Test boundaries

`test_group_raw_read_once.py` exercises actual POSIX regular file, symlink,
FIFO, missing/empty and bounded-size negative reads, plus substitution at the
open boundary. The existing synthetic all-six original raw archive suite is
also selected by the dedicated GitHub research CI in regular and `python -O`
mode. The external source/merge workflow's exact result is authoritative;
a queued job is not PASS.

Existing original physical Granite97 job:
https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38738835065

**NO MODEL PROMOTION / NO PRODUCTION EFFECT GRANT / NO 10T EQUIVALENCE CLAIM.**
