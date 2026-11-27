# Actual physical file-byte parity for eight Q24 Cell candidates

**Research only / SHADOW / DENY_ALL.** Stacked on the successful original
[#2377](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2377)
at `c8bd54d6e38a14232ef02eedf7b273660994b0f0`. This
does not change production V1, original Q24 semantics, active owners, CNS,
Final-use, signed artifacts, or independent NDU selection.

## Why an equal parameter count is not equal model size

The original hosted **physical training** run
[38850327138](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38850327138)
archived its SHA-256-bound producer/oracle receipts as artifact **12028396812**.
Independent local ZIP SHA256: `0205c7b117e8d9701c897aa42ab40d563f44e9c457cc1719ef97a57a7f00e47c`.

Original two tiers were approximately equal in *scalar count* but not in
physical bytes. Exact saved file lengths:

| Private parameter ceiling | V2 | V3 | SSM | minGRU |
| ---: | ---: | ---: | ---: | ---: |
| 2,048 scalars | 8,724 B | 9,516 B | 9,332 B | 10,948 B |
| 8,192 scalars | 34,084 B | 36,748 B | 35,908 B | 41,660 B |

This includes model-tensor payloads and serialized safetensors headers, and
confirms **25.49%** and **22.23%** largest-to-smallest file-size gaps.
A near-equal-parameter study is not a same-physical-byte study.

## New real-serialization byte-admission plans

Use *actual* pinned CPU PyTorch/safetensors serializer output for the precise
ABI: one immutable shared 32D feature vector; each private model gets a
trainable F32 32D→h Adapter, F32 1D Head, I64 Q24 fixed projection and
mechanism-specific I64 Q24 temporal weights. No empty padding or unused tensor
names; no proxy compression-ratio estimates. Enumerate width 5–256 and
minGRU rank 1–4; keep only those under the *serialized file byte* ceiling
and within 2% of its capacity. Before model training all template tensor
values are zero, so templates alone make **no trained model claim**.

| Serialized byte cap | V2 (width; bytes) | V3 | SSM | minGRU |
| ---: | --- | --- | --- | --- |
| 8,192 B | 54; 8,148 B | 45; 8,172 B | 47; 8,052 B | 38, rank 1; 8,156 B |
| 32,768 B | 224; 32,644 B | 191; 32,716 B | 201; 32,708 B | 166, rank 1; 32,756 B |

These two budgets use eight **different actual parameter counts**
(1,891/1,711/1,740/1,559 and 7,841/7,259/7,438/6,807), as a matter of
scientific honesty. The previous ~equal-parameter experiment remains frozen.

## Actual training and native Q24 acceptance

`near_matched_byte_budget.py` performs the encoded-byte preflight; the
original physical trainer now has an **explicit** `--physical-byte-budget`
option and an independent research schema, which trains, exports, reopens,
and checks actual saved file byte sizes for eight new physical models.
`neuron_near_matched_q24_shadow.rs` adds eight fixed file-byte geometry
registrations and rejects any budget-unit cross-labeling. The independent
Python integer oracle separately opens every model, verifies raw weight SHA,
count, dtype and physical file length, checks two fresh native Rust invocations
per candidate and exact Adapter/Head Q24 event parity.

The pinned physical workflow runs both original and byte-normalized studies
using the same frozen synthetic input case schedule. Each creates **eight
physically distinct files and sixteen Rust subprocesses**, with separate
receipt schema/identities. It never reuses one weight file under a different
budget name. The original A0 gate remains lightweight: Torch-only tests are
explicitly confined to the specialized CPU-trained workflow.

**HARD LIMITS:** file-byte parity is not peak resident RSS, optimizer memory,
full-model lifecycle, inference F32 parity, equal training CPU/FLOPs,
independently selected original V1 owner, authentic Encoder use, real task
labels, future utility, negative transfer, 4,096-scope host scaling,
CAS/signed Final-use, durable control or CNS routing. No single byte-matched
winner can be selected without those actual effects/evidence.

**Draft / NO_MODEL_PROMOTION / NO_MAIN_MERGE / NO_ROUTE_CUTOVER.**
