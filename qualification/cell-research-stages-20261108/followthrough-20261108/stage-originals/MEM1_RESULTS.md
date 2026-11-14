# MEM-1 reference pilot: implementation and retained results

Executed 2026-11-08 on ROG. **Reference execution completed; scientific and production qualification remain HOLD. Shared-model adoption: NoUpdate.**
The protocol is [PROTOCOL.md](PROTOCOL.md); production seams and missing owner integration are in [OWNER_INTEGRATION.md](OWNER_INTEGRATION.md).
Artifact identities and the raw-data package are indexed by [evidence.json](evidence.json). All percentages below are descriptive means over five synthetic stream seeds.

## 1. Decision supported by this pilot

Keep the new private fast-memory API opt-in. The exact-key RAG baseline is the strongest and cheapest arm in this task; this pilot provides no basis for replacing it.
Uniform replay improves retained A performance relative to the fast-memory arm without replay, at the cost of 128 extra updates. That comparison establishes the value of the extra rehearsal in this fixture, not a special consolidation advantage.
The registered structured selector loses to uniform replay on every seed in both conditions despite identical rehearsal counts and numeric-kernel work. Do not promote it as an improvement.
Stabilization helps the structured arm retain A, but it adds teacher compute and reduces B prequential accuracy. Its net benefit is not established.
No real-task confirmation, slow-adapter distillation, live owner integration, shared-model selection or production rollout occurred.

## 2. What was implemented

`FastMemoryV1` is a bounded normalized-delta associative matrix. State identity binds owner/Cell, scope and purpose, base/adapter digests, full owner snapshot, dimensions, numeric rule and update configuration.
Updates require an expected state digest and nonzero source-support commitment. A support-chain digest binds consumed evidence and numeric inputs. These bindings are not authentication; the caller must obtain current owner authority.
Checkpoint restore requires an external expected anchor and rejects mismatched identities, stale owner generations, corrupt bytes and invalid numeric state. An explicit reset carries predecessor identity but clears numeric state.
Predictions carry `DENY_ALL`. The library reranker only permutes an eligible recall selection; production integration must preserve the existing HNMF-selected set rather than replace HNMF selection with plain recall.
The native example uses the actual Rust kernel. Python owns the synthetic facts, replay pool, stream, accounting and process restarts; it does not reimplement the numeric kernel.

## 3. Execution and evidence boundary

| Record | Observed result |
| --- | --- |
| Upstream source | `732e934ba496d90fbe042b8d41d479ef901643e5` |
| Native validation scope | Exact-source projection of `hepta-memory-retrieval`, `hepta-cognitive-types`, `hepta-types`; full workspace not tested |
| Core tests | 53 passed; 2 existing explicitly ignored HNMF ceiling/performance probes; all 7 new fast-memory tests passed |
| Nextest run | `6bd99144-a8f5-4ccf-81d3-f09e246934e4` |
| Maintenance | Scoped `just fix` with warnings denied: exit 0; `just fmt`: exit 0; example rebuilt afterward: exit 0 |
| Test sequencing | No Rust tests rerun after fix/fmt, following repository instructions; final formatted sources match campaign manifests |
| Toolchain | Rust 1.96.0; just 1.51.0; cargo-nextest 0.9.103; Python 3.14.4; Linux x86_64 |
| Final example binary SHA256 | `59ea51c0c495a473a6cefc8c2a3649fc3d2263fa9d5c395e3d59982e5c1b0474` |
| Campaign completion | Dynamic 35/35; stationary 35/35; no failed arm/seed runs |
| Retained observations | 16,800 prequential events; 4,200 probes; 210 worker recoveries; 80 rehearsal candidates; 19,760 updates |
| Download verification | Full original archive SHA256 checked; both 35-run ledgers reverified locally; campaign source hashes match published source bytes |

The initial test wrapper failed **after the tests passed** because no fresh JUnit was emitted. The raw log contains 53 PASS records and the 53-pass/2-skip summary; the original error receipt is retained, not replaced by synthesized XML.
The installed nextest also warned that `profile.local.inherits` was unknown. The exact cause of missing JUnit was not established. This is not a complete JUnit gate or full-repository CI pass.
The original Mac source archive was truncated and rejected. The projection instead used independently hash-verified source files and explicit workspace/config transformations, retained in `projection-manifest.json`.

## 4. Registered comparisons

Each run consumes A1=96, B=104 and A2=40 observations. B contains 96 B examples and eight observations of A:8/A:9. Predict-then-update scores are kept separately from read-only probes.
The dynamic condition replaces A:8/A:9, revokes A:10 and removes A:11 from scope at B; it resets the private matrix, re-encodes eligible replay keys and rebuilds from eight eligible A records. Retention therefore includes that reset/rebuild policy.
The stationary condition retains owner generation and numeric state at B. It measures interference without that reset; it is not evidence of revocation handling.
All arms share resource ceilings and final owner checks. The four replay arms perform exactly 64 updates after A1 and 64 after B. Actual work is reported rather than artificially equalized.
`recurrent` uses fixed leaky-tanh features plus the same adaptive readout; it is not a tuned recurrent network or a no-fast-weight baseline. `rag` is exact-key current-fact lookup after exposure, not an LLM RAG system.

## 5. Retention and plasticity

Retention delta is A-stable accuracy immediately after B minus A-stable accuracy after A1. It excludes replaced, revoked and out-of-scope rules. B prequential accuracy is measured on 96 B examples before each update.

### Dynamic owner condition

| Arm | A after A1 | A after B | Retention delta | B prequential | A after return |
| --- | ---: | ---: | ---: | ---: | ---: |
| RAG | 100.0% | 100.0% | 0.0 pp | 87.50% | 100.0% |
| RAG + replay | 100.0% | 100.0% | 0.0 pp | 87.50% | 100.0% |
| Recurrent reference | 85.0% | 12.5% | -72.5 pp | 67.71% | 87.5% |
| Fast, no replay | 97.5% | 17.5% | -80.0 pp | 83.75% | 100.0% |
| Fast + uniform | 97.5% | 92.5% | -5.0 pp | 83.75% | 100.0% |
| Fast + structured | 97.5% | 70.0% | -27.5 pp | 83.75% | 100.0% |
| Fast + stabilized | 97.5% | 80.0% | -17.5 pp | 83.13% | 100.0% |

### Stationary owner condition

| Arm | A after B | Retention delta | B prequential | A after return |
| --- | ---: | ---: | ---: | ---: |
| RAG | 100.0% | 0.0 pp | 87.50% | 100.0% |
| RAG + replay | 97.5% | -2.5 pp | 87.08% | 100.0% |
| Recurrent reference | 20.0% | -65.0 pp | 66.25% | 92.5% |
| Fast, no replay | 25.0% | -72.5 pp | 81.67% | 100.0% |
| Fast + uniform | 87.5% | -10.0 pp | 81.04% | 100.0% |
| Fast + structured | 67.5% | -30.0 pp | 81.25% | 100.0% |
| Fast + stabilized | 90.0% | -7.5 pp | 75.63% | 100.0% |

Structured minus uniform after-B retention is **-22.5 pp dynamic** (paired seed differences -25, -12.5, -37.5, -25, -12.5 pp) and **-20.0 pp stationary** (-25, -37.5, -12.5, -12.5, -12.5 pp).
The B rehearsal ledger shows less source diversity: uniform consumes a mean 21.2 distinct sources in 64 updates dynamically, versus 10.6 for structured; stationary means are 22.4 versus 11.2. This motivates a diversity-control ablation; it does not by itself identify a causal explanation.
Stabilized minus structured after-B retention is +10.0 pp dynamic and +22.5 pp stationary. B prequential accuracy changes by -0.625 pp and -5.625 pp respectively, with 26,624 extra kernel multiplications per run in either condition.
All runs reach the registered 80%-in-16 B window. Dynamic median sample counts are RAG 31, RAG+replay 31, recurrent 51, fast/uniform/structured 35 and stabilized 37. Stationary medians are 31, 31, 62, 37, 37, 37 and 41. These are learning-curve milestones, not time-to-production-SLA estimates.

Final A accuracy hides interference with B. The final paired-constituent panel scores, dynamic/stationary, are RAG 100/100%, RAG+replay 90/82.5%, recurrent 37.5/35%, fast 55/52.5%, uniform 47.5/47.5%, structured 45/45%, stabilized 42.5/35%.
This panel combines two independently predicted labels; it does not demonstrate new relational reasoning or a learned composition operator.

## 6. Truthfulness and recovery

All 140 post-change revoked/scope probes in the dynamic condition abstain. Across all logged probes and online tasks there are zero invalid assertions, attributable to the shared synthetic owner gate, not to learned authority or general truthfulness.
There are **one probe and seven online stale-label assertions** in the dynamic condition. The probe is recurrent seed 0, after B, on A:9. Online stale counts are recurrent 3 and each of fast, uniform, structured and stabilized 1. These are eligible-source predictions of the old value, not restored permissions.

| Arm | Dynamic wrong probe assertions / 300 | Dynamic wrong online assertions / 1,200 | Stationary wrong probe assertions / 300 |
| --- | ---: | ---: | ---: |
| RAG | 0 | 0 | 0 |
| RAG + replay | 5 | 1 | 11 |
| Recurrent reference | 117 | 272 | 121 |
| Fast, no replay | 93 | 80 | 91 |
| Fast + uniform | 33 | 40 | 51 |
| Fast + structured | 56 | 56 | 66 |
| Fast + stabilized | 52 | 57 | 50 |

These denominators are all attempted queries, not only answered queries. Final stable-panel answer coverage is 100% in every arm, so the results do not rely on universal abstention. The exact-old-label counter is not a general citation/provenance validator.
All 210 native worker restarts restore witnessed state and the checked prediction/working-state values. The Python owner, RNG and teacher remain alive; complete owner crash recovery, cross-schema migration and uninterrupted paired trajectories were not tested.

## 7. Actual cost

The common reservation is 3,536 bytes of serialized native state plus recurrent vector, with replay payload capped at 16,384 bytes and numeric work capped at five million multiplications. Reservations are not measured RSS.

| Arm | Dynamic kernel multiplies | Stationary kernel multiplies | Dynamic wall ms/run | Stationary wall ms/run |
| --- | ---: | ---: | ---: | ---: |
| RAG | 768 | 768 | 37.97 | 40.13 |
| RAG + replay | 229,376 | 226,048 | 175.09 | 182.55 |
| Recurrent reference | 176,128 | 172,800 | 151.83 | 160.84 |
| Fast, no replay | 176,128 | 172,800 | 128.28 | 131.99 |
| Fast + uniform | 229,376 | 226,048 | 173.08 | 176.72 |
| Fast + structured | 229,376 | 226,048 | 173.91 | 177.76 |
| Fast + stabilized | 256,000 | 252,672 | 189.66 | 193.99 |

Numeric counts exclude hashing/IPC and are not FLOPs. Wall time includes orchestration and the common recovery checks; the binary is an unoptimized debug build. Timings are descriptive measurements from this harness, not an optimized implementation comparison.
Native child CPU, Python CPU, owner-call counts, peak replay payload, update counts, candidate bytes and per-seed values are retained in each summary. Uniform and structured match kernel work and update counts; stabilization does not match total work because its teacher predictions are charged.

## 8. Reproduction and remaining gates

From a full repository checkout, use the repository's `just test -p codex-hepta-memory-retrieval` workflow before `just fix -p codex-hepta-memory-retrieval` and `just fmt`. Do not rerun Rust tests after fix/fmt under current repository instructions.
Build `mem1_fast_memory` with Cargo, then supply that exact executable to the following commands. Fresh output directories are required.

```sh
python scripts/memory_cell_mem1/run.py --native /absolute/path/to/mem1_fast_memory --output /absolute/path/to/dynamic
python scripts/memory_cell_mem1/run.py --native /absolute/path/to/mem1_fast_memory --output /absolute/path/to/stationary --stationary
python scripts/memory_cell_mem1/verify_results.py /absolute/path/to/dynamic
python scripts/memory_cell_mem1/verify_results.py /absolute/path/to/stationary
```

The raw package retains both complete campaigns, inputs, before/after-maintenance patches, original error receipts, build/test logs, exact final source snapshots and the binary identity. It omits the compiled ELF; the original immutable native archive containing it is identified in `evidence.json`.
Scientific HOLD requires a frozen real-task panel, independent evaluator, adequate independent repeats, tuned strong baselines, matched useful resources and an advance practical-benefit threshold. Five synthetic seeds are not pretrained-model repeats.
Production HOLD additionally requires the actual current-owner provider, bounded persistent fast-state owner, Recall/Replay separation at real use, atomic revocation/adoption fencing, full crash recovery and a selected successor consuming an evaluated artifact.
No pretrained base/adapter is loaded here. Current sleep checkpoints rehearse private state; they do not create or adopt slow knowledge. The existing HNMF/adoption pipeline remains unchanged.
