# Historical training caches over persistent TCP peers

First execution: **9/9 parents passed**. All 36 spawned peer processes exited zero. Each peer began with only its own original shard and obtained the other contributions through the directed loopback TCP cycle. The coordinator supplied addresses and collected observations; it supplied no pooled statistics or reference weights.

Protocol: `92dc4c51de3d74f545da99165e2a0284286b6668`. Runner frozen before execution: `af560edc00de698ef821569ea55b50016e92f5fe`; execution tree including scope/provenance: `577fe0401b3285b937377b17e8b8d93e6df75816`. Exact Git blobs of all four imported/executed source files were checked before launch.

## First-run measurements

| Parent | Charged seconds | Sent application bytes | Sync rounds | Unknown delivery |
| --- | ---: | ---: | ---: | ---: |
| n8-s17011 | 0.405218 | 485,423 | 29 | 0 |
| n8-s27011 | 0.448868 | 479,803 | 23 | 0 |
| n8-s37011 | 0.322008 | 474,194 | 17 | 0 |
| n32-s17011 | 1.168727 | 6,009,469 | 33 | 0 |
| n32-s27011 | 1.076065 | 6,002,063 | 22 | 0 |
| n32-s37011 | 1.126329 | 5,997,777 | 24 | 0 |
| n64-s17011 | 3.231850 | 23,320,981 | 31 | 0 |
| n64-s27011 | 3.184678 | 23,372,649 | 48 | 0 |
| n64-s37011 | 3.585502 | 23,401,799 | 58 | 0 |

Every parent completed 12 offer frames: each of four initial batches propagated to the other three peers. Across all parents, successful `sendall` calls accepted **89,544,158 application bytes**, and actual `recv` calls returned exactly the same total. There were 108 offer frames, 285 synchronization rounds, zero refused requests, zero failed sends and zero unknown-delivery events. These byte counts exclude TCP/IP headers and retransmissions; `sendall` completion alone is not a remote receipt.

All four complete candidate objects for every parent equal the sealed #7200 candidate. Every candidate has revision four and 192 rows. The maximum absolute weight difference against the original archived `full` solution is **6.179154410368426e-12**, under the unchanged `rtol=atol=1e-7` threshold. No model/data/endpoint selection or correction followed the result.

Runner supervision used **14.555988 seconds** of the registered 600-second allowance; the complete outer process, including interpreter startup, took **14.800392 seconds**. The slowest parent was **3.585502 seconds**, below its cumulative 60-second allowance. There was one attempt, no reset, no timeout and no termination of a live child. The existing four synthetic transport controls were not rerun.

## Evidence and reproducibility

`attempt-1.tar.gz` is 570,770 bytes with SHA-256 `7c16c39ef70e7bae847fe2b33f68d7b23480c69ee94f23c5e79257d1310e9d01`. It retains 164 new evidence files: exact execution source, all child ready/final records and candidates, every synchronization-round log, budget journals, raw output, outer receipt, input bindings and formatting record. The inventory also records hashes of the 36 redundant local SQLite stores; their logical state is reconstructible from the frozen code and original inputs. The 63 fixed input/reference files are bound in `INPUTS.json` and already available in the #7200 archive with SHA-256 `f82a4f8d93ee940dff82c2c06a5c9492348bf6f589ae594d538aa40d42f79b28`.

Official `just fmt` returned zero on the partial checkout; qualification Python is outside its automatic dispatch. Ruff 0.15.13 then formatted the new runner, with equal before/after ASTs. Tests were not rerun after formatting. `SCOPE.md` identifies the POSIX/Linux supervisor and byte-meter semantics. `DEPENDENCY_PROVENANCE.json` transparently records a single trailing LF in the earlier #7198/#7200 executed helper; earlier artifacts and outcomes are unchanged, and this run uses exact repository dependency bytes.

## What this establishes

The fixed representation, declared sample identities, persistent head and candidate remain consistent across actual peer-to-peer propagation for these nine historical synthetic-source caches. The dense Gram statistics and JSON frames still impose substantial communication cost; the measured loopback result is not evidence of an end-to-end training speedup.

This was a manually specified cycle, not a learned Circuit. It introduces no new trajectories, optimization budget or final-test access and establishes no new-user generalization, provider permission, authenticated useful work, public-network resilience or Chain adoption/payment eligibility.
