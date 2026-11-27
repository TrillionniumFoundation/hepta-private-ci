# New HCSN C2 successor runner/controller (research-only HOLD_NO_GO)

This is a NEW candidate, NOT a restart, completion or overwrite of the original
desktop C2 job. Copied source identities were byte verified against the frozen
historical Git sources and are recorded in SOURCE-IDENTITIES.json. The original
files and old outputs remain unchanged.

The new runner uses crash-safe verified checkpoints and receipt-first, fsynced
event JSONL. The new controller uses durable per-attempt receipts, fsynced
journal, a fresh owner identity, and only structurally admits a terminal once
a wait4 result, cost and physical result file are present. A local PID is NOT
an authenticated heptaruntime durable job ID, independent replay or science GO.

The copied original contract/manifest has not been newly frozen or rebound,
so this code is NOT a runnable or adopted six-fit experiment. Separate new
freeze, manifest, input checks, native resource accounting, fault injection
and independent checkpoint replay are still required. Every P0-P5 gate HOLD.

## Explicit unadopted program manifest preflight (P0/P2)

`c2_program_freeze.py` is a **separate prospective** source/config byte
snapshot helper. By default it is strictly read-only, reports `HOLD_NO_GO`,
and exits nonzero if any of eight exact inputs or the sibling durable publisher
is absent. With the explicit `--write` flag it publishes a candidate
`PROGRAM-MANIFEST.json` once using checked, fsynced, no-replace bytes. It
never creates missing inputs, chooses a model/data/configuration, authorizes
an owner, resumes the old C2 job or executes a training step. The generated
manifest still requires an independent full source/model/data/config/owner
decision before any six-fit launch. The historical C2 objects are immutable.
