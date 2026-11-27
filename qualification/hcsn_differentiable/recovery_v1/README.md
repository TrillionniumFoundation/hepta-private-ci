# HCSN C2 successor: crash-safe receipts (research-only)

This is a **new, non-adopted successor I/O component**, NOT a retrofit of the
immutable original C2 job. Based on Draft HCSN #5920 at source
`4ed61beacd9e8cf08cd1f7f8c938b75d747149e4`. The original hard-failed/unknown outcomes,
torn 17th JSONL record and two zero-byte `interrupted.pt` files stay
unchanged and count against the original campaign.

## Why and exact scope

The original `c2_io.immutable_checkpoint` wrote directly into its final
`xb` filename, so a crash could leave a zero-byte file that could not
be retried safely. The original controller's `commands.jsonl` used flush
without an fsynced, per-record atomic commit. A missing controller `RESULT.json`
must not be reconstructed as if it had been published originally.

`c2_durable.py` supplies a POSIX-local standalone prototype for new
executions only:

- Checkpoints: serialize to a private temporary file; fsync bytes; enforce
  nonzero size, byte budget and **caller-supplied safe semantic validation**
  (frozen model, optimizer, RNG, source and data contract); rehash; hard-link
  without overwrite; fsync the parent directory. A post-link crash can leave
  the verified final file and an orphan temporary, **not** a success signal.
- Receipts: canonical JSON per event, strict contiguous sequence, owner start
  identity, SHA-256 content and previous-record byte hash, directory fsync.
  A cross-process lock serializes controller-thread appends. Missing/forged,
  duplicated, reordered, changed or partial receipts fail closed.
- The roster computes **producer completeness only**. Even six producer
  terminals retain `scientific_admission=HOLD` and
  `independent_native_verification=false` until independent native
  job terminal, resource cost, full stdout/stderr, model/checkpoint replay,
  full training-domain numerics and held-out training comparison are verified.

This uses POSIX atomic hard-link semantics with working directory fsync on
local filesystems. Remote/distributed and NFS behavior is **not qualified**.
Neither the code nor its tests authenticate a malicious host or provide
anti-rollback protection.

## Evidence and limitations

Run without torch or GPU:

`python3 -m unittest discover -s qualification/hcsn_differentiable/recovery_v1 -p 'test_*.py' -v`

Tests cover partial writer failure and hard process exit, permanent zero-byte
original preservation, no overwrite, corruption/gaps, duplicate terminals,
missing candidate proofs, forged identity, concurrency and success-language
separation. These are **I/O protocol tests**, not a measured GPU training
campaign or failure-injection in the original kernel process.

## Next integration gate (still open)

1. Freeze a **new** C2 source/model/runtime/program manifest, not old output paths.
   Integrate successor calls at original `c2_runner` checkpoint
   sites and at both original `c2_controller`/runner JSONL record sites.
2. At restart, verify each complete receipt, safe checkpoint load, original
   owner process identity, and full native per-child `wait4` cost.
   Never automatically retry an unknown-effect original attempt.
3. Inject SIGKILL at serialization, checksum, link, directory commit, final
   controller publication and restart boundaries; test missing/duplicate
   terminals and every resource bill with full denominator.
4. Run all six successor fits under matched resources; independently replay
   every model and evaluate P1 numerical domain before any P2 science claim.

Status: **HOLD_NO_GO**. A local test pass cannot establish training recovery,
numeric accuracy, scientific superiority, CI-wide success or production Go.
