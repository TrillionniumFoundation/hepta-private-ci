# V23 — Real archived mmBERT features: physical packed Head readout at 64–4096 slots

**2026-10-16 · DRAFT / SHADOW_ONLY / DENY_ALL. NO production qualification or scientific model promotion.**

## Scientific purpose and immutable base

Frozen parent: `TrillionniumFoundation/hepta-private-ci` PR [#2364](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2364), originally inspected exact HEAD `4c878ed845482d759432930f7ddfaff9f5f82a56`. This is an **additive research-only execution-data-plane experiment**. Do not touch earlier V5–V22 sources/results, original selected production Cell, native Rust Worker, independent NDU, Artifact CAS, CNS, generation fencing, FinalUse or `main`.

The original [GitHub run 38546717991](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38546717991), Artifact `11890616195`, contains the immutable 128×384 FP32 frozen Encoder snapshot from real `jhu-clsp/mmBERT-small`, repository revision `abc32620dd4f6ab06f5fbe905dc25f310618e09f` and 128 original AG News publisher records. Original ZIP SHA256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`; saved feature file SHA256 `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`; input/source roster SHA256 `d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a`.

V23 reloads original **V16 seed 41 trained two-Head weights** (SHA256 `4dc71c47b4ec297ce65a221adabd8ad7888cdd1c1ce2f67a7aee3986d4a1433e`) and the shared V15 normalizer, using V20's original frozen-weight verifier. It uses **exactly four original TRAIN feature vectors** as label-free input probes. No actual new pretrained Encoder forward, no text-generation Reader, no new heldout labels, no future input, no fresh learned Head training. This is not an equal-lifecycle comparison against a 421M checkpoint.

## What is physically allocated

There are exactly **two independently trained Head parameter VALUE sets**; V23 allocates physically separate FP32 Head storage slots at `64, 256, 1024, 4096`, alternating the two archived Head weight values across the slots. This is a real CPU allocation, **not 4,096 independently learned Cell skills**. Each Head contains a 384-to-4 linear layer with bias: 1,540 FP32 scalars/slot. A 32-Head selected subset is materialized ONCE before the timer to avoid per-request Head weight gathering; its extra **197,120 bytes are charged**, not hidden. Four original normalized features are held once each and shared by all Head slots; the measured kernels do not allocate per-Cell copies of that input.

All four original frozen features and exact saved Head logits are verified: a Python per-Head loop and NumPy `einsum` packed CPU implementation must reproduce the same top-class output and logits within `1e-5`. Full population and preselected 32-Head outputs are separately checked. The 32 active Head IDs are deterministic, **not a learned gate or authorized CNS route**. Kernel timings include Python/operator/output allocations; they exclude Head selection decision, Worker queues, all source-authorization lookups and full production service accounting.

## Two genuine local CPU executions (NOT user's dot/target device)

Each size runs in a **different real Linux Python CPU process**. For each process, 8 unmeasured warmups and 128 timed repeated operations are executed for each of four kernel profiles: full per-Head loop, full packed, preselected 32 per-Head loop, and preselected 32 packed. Timed profile order rotates per repetition. `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`; raw per-call elapsed and process CPU times, p95/p99 and Linux whole-process peak RSS are captured. The complete physical execution was separately repeated in a second process for each size (8 processes total). Both independent read-only NumPy audits rechecked the exact original source and model bytes, all 4×4 saved-score digests and every reported timing percentile.

**p99 is per-kernel milliseconds**, not an end-to-end SLA; each value is the 99th-percentile interpolation over only 128 sequential repetitions. Repeated CPU runs have substantial real host noise. No results are silently dropped or selected by best outcome.

| Head slots | Base allocated weight bytes | Charged cached 32-Head bytes | Whole process peak RSS (KiB) A / B | Full per-Head p99 (ms) A / B | Full packed p99 (ms) A / B |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 394,240 | 197,120 | 101,964 / 101,944 | 0.321 / 0.775 | 0.053 / 0.057 |
| 256 | 1,576,960 | 197,120 | 103,244 / 103,076 | 2.863 / 3.664 | 0.553 / 0.578 |
| 1,024 | 6,307,840 | 197,120 | 108,044 / 108,132 | 12.912 / 6.721 | 2.247 / 1.745 |
| 4,096 | 25,231,360 | 197,120 | 126,572 / 126,592 | 33.681 / 19.442 | 15.696 / 4.657 |

The 4,096-slot values are **not stable**: independent full-packed p99 differs by more than 3× across two instances. This must be retained; never claim a stable throughput/performance win from only two samples or an end-to-end worker p99. The host process RSS includes Python, NumPy, the original tensors, allocated Head slots and the cached active Head bank; Head-only bytes are not RSS. No GPU, energy, queueing, actual 4,096 independent concurrent source scopes, WAL or crash/recovery was measured. Runtime only counted CPU kernel work and existing original model inference on cached features.

## Independent readback and negative controls

`v23_original_feature_batch_cost.py` is the CPU producer. `v23_original_feature_batch_cost_review.py` does **not import that producer**: it independently opens the original V15/V16 safetensors, recomputes all frozen real-input score identities and four-size physical occupancy, rereads every raw 128-point latency series, and recalculates p95/p99. `v23_original_feature_cpu_summary.py` imports neither numerical producer nor reviewer; it only accepts **two complete, already independently reviewed** four-size evidence panels whose source SHA, numeric probes and canonical receipt digests agree. Its create-only sanitized summary is `STEM_V23_ORIGINAL_FEATURE_PACKED_CPU_RESULT_20261016.json`. The Git tree contains none of the original texts, labels, pretrained Encoder tensors or trained model weights; these remain in the private local/hosted experiment staging area.

The V23 tests cover physical storage occupancy, independent storage rather than fake 4,096 aliases, cached weight-byte charges, packed vs loop forward equality, feature SHA/case census, missing/symlinked/modified original source, missing/duplicate fleet sizes, bogus p99 series, fake slot budgets, reordered active IDs, forged model score digests, changed producer code SHA, false source authority, false target-host proof, fake future data and false production admission.

**Actual local V23:** 36/36 normal and 36/36 `python -O` tests, with real archived original features and actual saved V16 model weights, zero skips. On the first V23 implementation (before the bounded 32-Head cache and cross-run summary), the inherited V14–V23 full normal suite ran **295/295 PASS**. After final V23 edits, current 36/36 tests were rerun in both modes, but final full 302-case **single-process** combined run timed out on this container and is **not a PASS claim**. The pre-existing V14–V22 266-case original-data normal and optimized green receipts remain historical evidence at unchanged source identities, not new exact-head CI. All GitHub exact-HEAD hosted checks, global `blocking-ci`, formatter, Cargo, Architecture and native signed Worker/FinalUse remain independently pending.

## Commands on the original immutable material

```bash
cd qualification/stem-cell-v1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export HEPTA_V23_ORIGINAL_INPUTS=/private/v14-input
export HEPTA_V23_ORIGINAL_V15=/private/v15-candidates
export HEPTA_V23_ORIGINAL_V16=/private/v16-candidates
for replica in A B; do
  for n in 64 256 1024 4096; do
    python v23_original_feature_batch_cost.py --inputs "$HEPTA_V23_ORIGINAL_INPUTS" \
      --v15 "$HEPTA_V23_ORIGINAL_V15" --v16 "$HEPTA_V23_ORIGINAL_V16" \
      --cells "$n" --rounds 128 --out "/private/v23-${replica}-${n}.json"
  done
  python v23_original_feature_batch_cost_review.py --inputs "$HEPTA_V23_ORIGINAL_INPUTS" \
    --v15 "$HEPTA_V23_ORIGINAL_V15" --v16 "$HEPTA_V23_ORIGINAL_V16" \
    --receipt "/private/v23-${replica}-64.json" --receipt "/private/v23-${replica}-256.json" \
    --receipt "/private/v23-${replica}-1024.json" --receipt "/private/v23-${replica}-4096.json" \
    --out "/private/v23-${replica}-independent-review.json"
done
python v23_original_feature_cpu_summary.py --evidence /private \
  --out /private/new-v23-no-go-aggregate.json
```

PR-side CI runs the source-only Mechanism tests, and the existing source-bound **push** workflow runs original V14–V16 data/model production, the eight bounded V23 child measurements, two independent reviewers, the summary and the actual-input adversarial test suite. Only the sanitized aggregate is allowed as a hosted artifact; no private model/data/case-level predictions or signer material is uploaded.

## Decision / strict remaining gates

**Descriptive CPU kernel parity and operator cost measured; no scientific Cell Split gain identified.** V23 is `DRAFT / SHADOW_ONLY / DENY_ALL`; no new model winner, no automatic division, no native Worker route, no NDU/CNS owner change, no signed production FinalUse, no `main` merge.

Next gate requires actual SOURCE-DISJOINT future1/future2 after Oct 17, independently authenticated source publisher/executor/evaluator/host, physical pinned Encoder text-to-feature attestation, old-task negative transfer, complete 64–4096 Cell Worker end-to-end CPU/RSS/energy/p99 and real WAL/CAS/CNS crash recovery. These measurements cannot be inferred from duplicated fixed Head tensors, even if packing reduces this local kernel's apparent execution time.
