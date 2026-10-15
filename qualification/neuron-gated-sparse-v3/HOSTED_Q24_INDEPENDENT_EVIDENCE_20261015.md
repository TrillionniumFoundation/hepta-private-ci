# Exact hosted Q24 physical evidence: independently observed limits

**Research-only / `DENY_ALL` / `NO_MODEL_PROMOTION`**  
**Frozen native source:** [PR #2097](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2097) at `3621977ee2487af53400c9c1bd07ff06928b77cd`.  
This document adds a read-only consumer analysis; it does not change V1/V2/V3/SSM/minGRU kernel code, native Worker, model-loader ownership, persistent checkpoints, selected production weights or `main`.

## 1. Two original physical CI artifacts, not a production model experiment

| Provenance | Actions run / artifact | Uploaded ZIP SHA-256 |
|---|---|---|
| 20 physically loaded trained-shadow Q24 native slots | [run 38667249963 / artifact 11945633077](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38667249963/artifacts/11945633077) | `9c871918e306f6f0fa0c6f3864bd75ff9271df3829ce8b58108618fc99e93995` |
| V1/V2/V3/SSM/minGRU × 64/256/1024/4096 *mechanism-only* fixture | [run 38667249967 / artifact 11945529544](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38667249967/artifacts/11945529544) | `f65886ca41941de185dd2af8bb9f05221933e9208e078889179dc5671650834b` |

An independent local analysis downloaded both exact ZIPs via the GitHub connector, recomputed complete ZIP SHA-256 hashes and matched the SHA-256 values recorded in the original Actions artifact-upload logs. It did not authenticate publisher weight provenance, independently attest actual host custody, verify NDU benefit or verify real production A0 enrollment.

## 2. Distinct physical weights ≠ nominal parameter ceiling labels

The trained-Q24 research artifact reports 20 arm/budget positions (V2, V3, diagonal SSM, low-rank minGRU at 2K/8K/16K/64K/262K private-parameter ceilings) and 40 fresh native process invocations (two per position). Recomputing the set of physical weight hashes from **the 20 row payloads**, without using the summary's supplied count, yields:

| Temporal arm | Slots | **Distinct weight digests** |
|---|---:|---:|
| V2 | 5 | 1 |
| V3 | 5 | 1 |
| Diagonal SSM | 5 | 1 |
| Low-rank minGRU | 5 | 2 |
| **Total** | **20** | **5** |

The source's independent realized-budget guard correctly reports `five_tier_exact_realized_parameter_design_valid=false` with duplicated cross-tier weights and unequal realized parameter sizes. Treating 20 names as 20 independent trained models is forbidden. Distinct weight hashes also do **not** establish independent experimental data, same training compute, or superior task utility.

The source run's Q24 research Head/logit and sign-margin integer oracles matched on 20 positions; six negative native inputs were rejected; two fresh OS processes agreed bitwise per position. But the archived receipt explicitly says `floating_torch_native_q24_prediction_parity_verified=false`, `full_selected_model_head_executed=false`, `crash_durable_recovery_verified=false`, `frozen_a0_owner_revalidation.a0_rechecked=false`. Research-native integer-Head parity is **not** full trained F32 → native-policy equivalence.

## 3. Mechanism-only resource observations at 4,096 logical Cells

| Arm | Fixture p99 mechanism tick (µs) | p99 vs V1 | Fixture throughput tick/s | Process peak RSS (MiB) |
|---|---:|---:|---:|---:|
| V1 | 164.744 | 1.00× | 5,619.7 | 10.38 |
| V2 | 205.812 | 1.25× | 4,585.1 | 10.40 |
| V3 | 352.065 | 2.14× | 2,802.4 | 11.98 |
| Diagonal SSM | 326.355 | 1.98× | 2,975.4 | 10.97 |
| Low-rank minGRU | 363.622 | 2.21× | 2,685.0 | 10.84 |

These measurements are from a synthetic 32-channel trace of eight sequential events per logical Cell, within isolated CI processes. They exclude the true Encoder, projection, Head training, inference queue, Artifact CAS, WAL, signatures, generation fence, restoration, GPU and end-to-end NDU. They are **not** target-host p99 or an argument to change production V1. Differences indicate that a true NDU/resource comparator must charge the measured temporal mechanism cost.

Original isolated Rust workflow: 126 crate tests, 3 trace-probe tests and 5 Q24 Head tests passed. Mechanism-only run declares `trained_artifacts_qualified=false`, `target_host_qualified=false` and `parameter_budgets_matched=false`.

## 4. Independent negative-path recheck

A separate offline Python 3.13 read-only audit of the exact artifact ZIP checked outer ZIP bytes, member bounds, duplicate JSON keys, 20 slot identities, 40 process counts, hashes of the physical weight results, original signed-status **claims** (not cryptographic issuer verification), Q24 integer oracle fields, invalid native-input tests and explicit no-promotion flags. **14/14 local tests passed**, including tampered ZIP, fabricated distinct-model count, forged A0, forged F32/native parity, missing second process and changed matched-budget claims.

This local reader is a bounded descriptive research checker, not a new Evaluator, Selector, Executor, signer, production loader, or independent attestation service. A matching ZIP SHA only binds bytes to the pinned hosted source and cannot prove that those bytes came from production workloads. The offline script/report is independently retained outside this PR; this document deliberately does not claim that a new GitHub source-level audit test has run.

## 5. Remaining hard gates

1. **A0 blocked:** Independently identify currently selected production Cell weights, model generation, current checkpoint, Scope, state-owner and real host.
2. **A1/A3 blocked:** Train physically *distinct and parameter/compute matched* five-arm variants under each declared ceiling, reload exact tensor bytes and recompute same-case prediction/Head/state parity.
3. **A4 blocked:** Execute genuine full 64/256/1024/4096 Cell target-host profiles including Encoder, Worker batching, queue, WAL/CAS, authentication, recovery and p95/p99/energy.
4. **NDU blocked:** Preserve frozen no-change, positive independent future-window decision utility, old-task retention, negative transfer, OOD, refusal/abstention and calibration.

**No merge to production and no model promotion.** All candidate results remain Shadow and `DENY_ALL`.
