# Original current-cut checkpoint: executed memory and candidate Agentd composition

Source commit: `9e1521d2ac6d171a0c307e2ae5a3b7a1ee6cacd0`.
Source tree: `9c13c3ffbbce2b40ec9d86f82cff129d173040a2`.
Parent: `45f1e7d471c9e0720ce2c149da92629f785a01a4`.

The existing ProductionDurableWriter now checkpoints the current original
CognitiveStore cut without requiring a retained chat request or creating another
send right. It holds the original write serialization through exact external ACK,
checks the existing live lease before and after, and rolls back on refusal,
timeout, mismatched ACK or cancellation. The original host composition retains
the same writer/publisher and performs bootstrap ACK after the Notes descriptor
handoff but before the original final synchronous installation.

## Actual final-source execution

The final ten-source manifest is SHA-256
`09413d3a8fc09d14e81a78202a4cd7baa051a0ef3610c6d51132811b1580f78e`.
The original 9,111-blob workspace plus its recorded 25 source overlays was used;
it was not presented as a complete Git checkout of the later evidence commits.
The original Cargo lock and compiler/profile were retained, and all source/mode
checks before and after the commands matched the recorded inputs.

| Gate | Actual result on final source |
| --- | --- |
| Original `just test --locked --cargo-profile dev-small --build-jobs 1 --test-threads 1 -p codex-hepta-memory --lib` | 327 pass, 8 original skipped; test time 110.740 s |
| Original scoped `just fix` for the memory library | Exit 0, no source or lock rewrite; lib-test 26 warnings, lib 2 duplicates |
| Original final `just fmt --check` | Exit 0 |
| Candidate owning-CI parser on the actual final local JUnit | All 327 cases and all 10 required exact memory names accepted |
| Agentd library, nine factory/six Notes/three bridge tests | Not executed in these records |
| Production backend, signing/permission inputs, devices or native guest | Not qualified |

Actual local tools were Rust **1.95.0**, nextest **0.9.149**, and just **1.40.0**.
The owning GitHub CI separately pins nextest **0.9.103**; its execution is still
pending. A local parser check on a 0.9.149 report does not requalify that pin.
The original warning policy was preserved; these are not `-D warnings` results.
Three direct SQLite connection warnings were removed by using the existing
codex-state SQLite shim, detaching a genuinely independent connection, and
retaining the original immediate BUSY=5 checks. No allow annotation was added.

## Complete record and historical attempts

`raw-evidence.tar.gz` retains the complete frozen `checkpoint-current` source,
base/preimages, revisions, publication manifests and raw validation records;
the guard/probe records under `checkpoint-current-validation`; the independent
checkpoint and SQLite reviews; the complete owning-CI source and synthetic
sentinel checks; and root's actual-JUnit parser/readback records. Dependency
cache payloads, evolving Agentd budget/execution records and Python bytecode
caches are excluded. Later Agentd execution belongs to a separate archive.

The first memory attempt stopped at the unchanged RAM guard and is retained as
a controlled stop, not a pass. The second attempt passed the prior direct-SQLite
candidate. The third attempt and final quality gates qualify the revised shim
candidate. Their original stdout, stderr, JUnit, tool binaries' hashes, exact
commands, source inventories, timing and resource observations are all retained.
`manifest.json` lists every raw member and its hashes; full archive readback
matched every member. The 11-source GitHub tree readback covers all 9,251 leaves.

```sh
python3 -m tarfile -e raw-evidence.tar.gz extracted
```

No production checkpoint backend is fabricated. The new factory inputs still
require original trusted authority and a real publisher supplied by the original
system. Terminal retirement checkpoints, every other writer mutation, crash
recovery, actual Agentd composition and complete seven-input production evidence
remain independent gates. Notes descriptor handoff is not a claim of Notes
content persistence.
