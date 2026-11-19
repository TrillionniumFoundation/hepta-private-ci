# Original RunStart physical read view: new recovery candidate

This candidate is rebuilt from the actually available base
`106f5e41f2ff8421c5aad10eeb746d453ed00563`. The earlier transient workspace's
unpublished reader and its native results are not reused as evidence for this
tree. `candidate.json` records every local-to-remote commit mapping, identical
tree identities, changed blob identities, and retained log hashes. Raw logs are
losslessly gzip-compressed with deterministic metadata; both compressed and
uncompressed hashes are recorded. Their original whitespace is preserved.

## What this source provides

The original `DurableRunStartJournal` and the new Unix
`ReadOnlyRunStartViewV1` use one framing parser. The extraction preserves the
writer's existing complete-frame validation, sequence, canonical record decode,
record and chain digests, duplicate-run refusal, bounded records, and original
recovery policy. Only the writer retains its existing incomplete-tail repair.
Actual frame ranges come from the original cursor and physical frame length;
they are not obtained by re-encoding a legacy record in the current format.

The view consumes an already existing, regular, O_RDONLY file descriptor. Safe
`rustix::fs::fcntl_getfl` checks the actual descriptor access mode. It does not
open a path, create, write, append, truncate, repair, take the writer's flock,
sign, or implement a writer or authority trait. It therefore can observe an
original journal while its original writer still holds the exclusive flock.
The view binds the descriptor's device/inode, original profile digest, journal
binding, explicit external RunStart anchor, and bounded record count.

Each observation reads a bounded physical image, validates the complete history,
then independently reads the physical bytes and metadata again before returning.
Complete, fully validated records after the external anchor are allowed, but only
records at or before that anchor are returned. An incomplete tail is refused;
it is never repaired or treated as complete. Once a complete tail has been seen,
that handle accepts only append growth with the entire seen prefix unchanged.
All observation errors poison that handle, including an unsuccessful final
physical reread. Restoring old bytes does not clear its refusal.

`read_with_frame_at_original_prefix` validates the caller's retained prefix and
locates the record in the same physical image. It returns the original record,
publication tuple `(sequence, record_digest, chain_digest)`, actual frame bounds,
and observed physical length. The caller must separately require a new frame
after its independently retained baseline. The prefix API alone does not do so.

## Authority and recovery limits

An anchor supplied to this library is a data consistency input. Neither this
reader nor its fixture signatures prove an independently acknowledged Objective,
Root authority, an authenticated admission, a successful task, an Outcome, or an
independent evaluator. The actual original owner must retain its successful
append-and-sync receipt through the authenticated Root lane, with the original
profile and descriptor custody, and authenticate the original signed admission
against the actual current trust and revocation state.

Refusal here is intentionally per handle. The real-file tests explicitly permit
a fresh view after old bytes are restored; persistent cold refusal requires the
independent Root-owned durable marker and its original ownership protocol.
The API proves observations of the retained descriptor, not that a pathname
continues to name its inode. A real rename/replacement test preserves that limit.
Windows is explicitly excluded from this Unix descriptor-mode API.

## Results and exact scope

At local `14eefbe4114483ec73683482ad0f9c3a68475749`, remote
`e471021382675020e53cf984b7f067d33a7a02bb`, tree
`3358b29f672b49f4dd2c5870b2fcc1d86dffb449`, with a clean worktree:

- **10 source-closure tests passed.** They test real guard mutations, including
  comments and an unrelated helper attempting to supply removed physical gates.
- **372 protected-file rows passed; 504 inventory entries matched declarations.**
  This did not execute the full repository caller scan.
- Source and tests passed `just fmt`; the guard-only stage reported no changed
  files requiring formatting. `git diff --check` passed.
- **13 new real-file native tests are authored and have not run here.** They
  cover actual locked-writer coexistence, descriptor modes, profile/anchor
  mismatch, corruption/restore, partial tail, complete-tail rollback/rewrite,
  a real append between physical reads, conflict frames, retained-inode behavior,
  legacy/current frame ranges, and original-prefix checks. These are not native
  passes. Existing writer tests also need execution after the shared extraction.

The global caller verifier and its ignore rules are unchanged. Three protected
source rows were added and the existing CALLERS exact-byte allowlist was rebound.
Because the existing global function-order grammar does not accept generic
function markers, the new QA additionally scopes its existing order primitive to
the uniquely located actual `with_observation<T>` body, rejecting nested or
unrelated function substitutes. It does not weaken or normalize the verifier.
The data-only view adds no privileged inventory entry or authority capability.

## Actual dependency gates, including failures

The Unix crate edge uses the workspace's already locked `rustix 1.1.5` with `fs`.
The Cargo lock change is exactly the learning-ledger package's dependency edge.
Cargo resolution and native compilation remain pending in this executor.

The first actual `just bazel-lock-update` exited **127** because Bazel was absent.
Official Bazel **9.3.0**, matching `.bazelversion`, was then installed only in the
task's tooling directory. Its SHA-256 was checked against the official release:
`d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8`.
The next actual update exited **37** because Bazel's embedded JVM did not trust
the environment's supplied CA. Both failures and their original logs are retained.

A task-local Java trust store copied the system Java roots and imported the
inherited `SSL_CERT_FILE`. Proxy settings remained inherited and TLS verification
remained enabled. The next **actual lock update exited 0** (255.282 seconds).
The repository's **actual `just bazel-lock-check` exited 0** (35.564 seconds),
invoking `mod deps --lockfile_mode=error`. The metadata records the exact Cargo
and MODULE inputs before and after. `MODULE.bazel.lock` remained byte-for-byte
unchanged, SHA-256
`783b3ad329fa53bd4a0e48be6907d38259fa2880d61bd1994b863d7f78bbca57`.
No generated lockfile was hand-edited, and no Bazel build or test pass is claimed.

Full ordinary-chain qualification remains **positive 0 / NoUpdate 0 /
daemon-plus-Root cold restart 0**. The next native gate is the real
`codex-hepta-learning-ledger` library suite with zero retries; the main thread
owns the shared native target and the separate integration candidate.
