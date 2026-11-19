# HCSN C2 successor: exported result JSON and log flag fail-closed

2026-11-11; DRAFT, engineering-only; HOLD_NO_GO. Stacked on #5968
at exact base eacc1cd2d85a89dff5e71b5de4e406e5dbea5ff4.
No original C2 process restarted, no historical logs or checkpoints edited,
no independent native status or model science implied.

## New attack and correction

The previously deployed exported-native structural verifier checked
result.json SHA-256 but did not parse its JSON. A producer and copied receipt
could agree on bytes containing duplicate keys, NaN or a top-level array
and still appear structurally matched. A second fail-open permitted
log_truncated=0 or numeric zeros within its stdout/stderr mapping,
because Python numeric zero compares equal to boolean False.

Five adversarial tests each construct fresh synthetic copied evidence
bound to its OWN current receipt hash, without forging any hash.
RED: native heptaruntime desktop job 1a1caa06838-2564-76b,
19 targeted tests, 5 failures, exit 1. Exact RED.stderr.log
SHA256 62b8aa988571c9d16d3830e6cea73d58e287bd9c6a2f26fb82d530c5cba027e2.
GREEN: desktop job 1a1caa17cc2-2564-774,
full recovery_v1 57/57 tests pass, zero skips, exit 0.
Exact GREEN.stderr.log SHA256
2b80be868a44abcffcf391cf27c2e1c0246c75047ad2f6ad2695147ad61f6196.
Python 3.12.3 and Torch 2.8.0+cu128, original C2 pinned interpreter.
Original final test-source Git blob is
83fd93dac91a291ae010501256e7325d1a982acc.
New verifier-source Git blob is
43e7a7fb77332af29a24a450f67dfe70bc2c0e88.
RED and GREEN full stdout/stderr, exit and Python environment are retained here.

The fix uses strict JSON object parsing with duplicate-key,
NaN, Inf and overflowed exponent rejection, preserving the original
16 MiB result size limit. The native log flag must be literally false
or exactly both literal false stdout/stderr values. It is still
only structural checking of copied evidence: result semantics, authentic
live supervisor status, model replay and science require separate proofs.

## New read-only original C2 observation (not the synthetic fixture)

The fresh byte inventory, ORIGINAL-C2-READONLY-STATUS.json, has SHA256
4a2c0794f84ba3824345f729e6edadafb6645fc949bfa95733051311bb9c6c46.
Desktop job 1a1caa7a9e5-2564-7ad exited 0, against original frozen
path inventory without writing those source files. The original C2
native supervisor 1a1c74f3308-be2a-75 separately remained
finalizing / outcome unknown / status_authoritative=false /
terminal_publication_confirmed=false.

Four original result.json paths match their pinned full SHA256, only
4 of 6 producer results exist; the other two remain missing. Both
interrupted.pt are zero-byte with original empty digests. Original
commands.jsonl stays 28,672 bytes with SHA256
1405bced8c59a294276616cd7054f2b4068e10d858ab61d78bb578b93992239f,
16 complete newline JSON entries and torn remainder.
Original controller RESULT.json still absent.

New current-path discrepancy: the two original best.pt live paths
previously listed in frozen #5920 FIT-INVENTORY-READONLY.json
are now absent from the original fits directories. Those directory mtimes
read 2026-11-11 06:03 local filesystem time. This observation does NOT
establish when or why they disappeared, nor does it invalidate archived
copies or prior frozen hash assertions. The first read-only attempt
1a1caa50525-2564-794 exited 1 on the unexpected missing best.pt paths;
the corrected read-only inventory explicitly records the absence
instead of silently treating the frozen inventory as current.

## Gate boundary

P0 E,C,U,F,G,J,M/CURRENT/source/model/data/config/log remains HOLD.
P1 actual visited posterior, drift +/0/-, near-boundary and low-noise,
short/long, rare-tail/log-risk, reset/mass/count and high-precision AD
remain HOLD. P2 new genuine durable runner/controller integration,
six independent full fit terminals, true native costs and replay,
common frontend/head/budget/tuning opportunity GRU/CfC/SNN/event
gradient/SSM/optimized Transformer/HCSN comparison remain HOLD.
P3 independent QVI versus fixed and trainable thresholds remains HOLD.
P4 real async multimodal and anti-diffusion controls remain HOLD.
P5 hardware/production adoption remains blocked on stable independently
verified net benefit. No Go, merge, claim of scientific improvement or
restart of original unknown-effect job is authorized by this patch.
