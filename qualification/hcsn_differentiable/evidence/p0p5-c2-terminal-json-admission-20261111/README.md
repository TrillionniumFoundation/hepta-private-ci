# C2 terminal result strict JSON admission — P0/P2 HOLD

Parent exact source head: `1038b6c2f1246035385549bbd648ca2a5fa02121`.

This isolated change rejects ambiguous untrusted *terminal result.json* even when a path/hash check matches its bytes: duplicate JSON keys anywhere in the structure, NaN/Infinity and float overflow, malformed UTF-8, and files exceeding the 16 MiB admission cap. It compares parsed bytes to the independently measured identity and retains real process CPU/wall evidence if result verification is rejected.

Tests use a **source-extracted AST of the actual terminal_result_gate**, injected with deterministic stdlib dependencies on Python 3.12.3, **not** a real Torch model or C2 training execution. RED 6 cases / 4 failures (process exit 1) on the unchanged parent source; GREEN 6/6 (exit 0) after the fix. Logs and precise digests appear in EVIDENCE.json. A new mandatory CI test invocation has been added. The exact new source head still requires its own GitHub Actions run.

Original desktop C2 was inspected read-only in ORIGINAL-READONLY-REHASH.json: 4/6 producer results, 2 zero-byte interrupted checkpoints, one torn journal line, no authoritative controller RESULT; 0/6 independent full-model replay. The original job was not restarted or modified. Full P0–P5 and production remain **HOLD_NO_GO**; this is only evidence admission hardening.
