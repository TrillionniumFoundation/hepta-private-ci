# C2 terminal result strict JSON admission — P0/P2 HOLD

Parent exact source head: `1038b6c2f1246035385549bbd648ca2a5fa02121`.

This isolated change rejects ambiguous untrusted *terminal result.json* even when a path/hash check matches its bytes: duplicate JSON keys anywhere in the structure, NaN/Infinity and float overflow, malformed UTF-8, and files exceeding the 16 MiB admission cap. It compares parsed bytes to the independently measured identity and retains real process CPU/wall evidence if result verification is rejected.

Tests use a **source-extracted AST of the actual terminal_result_gate**, injected with deterministic stdlib dependencies on Python 3.12.3, **not** a real Torch model or C2 training execution. RED 6 cases / 4 failures (process exit 1) on the unchanged parent source; GREEN 6/6 (exit 0) after the fix. Logs and precise digests appear in EVIDENCE.json. A new mandatory CI test invocation has been added. The exact new source head still requires its own GitHub Actions run.

Original desktop C2 was inspected read-only in ORIGINAL-READONLY-REHASH.json: 4/6 producer results, 2 zero-byte interrupted checkpoints, one torn journal line, no authoritative controller RESULT; 0/6 independent full-model replay. The original job was not restarted or modified. Full P0–P5 and production remain **HOLD_NO_GO**; this is only evidence admission hardening.

A **separate full local C2-successor unittest discovery** was also run using the *actual existing pinned desktop training environment* (Python 3.12.3, Torch 2.8.0+cu128, NumPy 2.3.5). It passed **38/38 tests, zero skipped** on exact source commit `4ab961d340134d93d64aa999290f8ed65cf1cc0d`, durable job `1a1cc907477-2564-faa`. This includes synthetic successor wiring and an actual Torch serialization round-trip, but **does not** create six C2 terminal fits or replay existing producer checkpoints. Original raw logs and SHA-256 are retained in NATIVE-RESULT.json. The final published head differs by **evidence files only** and needs its own Actions validation.
