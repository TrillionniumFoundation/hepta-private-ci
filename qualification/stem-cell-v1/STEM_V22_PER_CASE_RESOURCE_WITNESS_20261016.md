# V22 — Original-case-bound latency witness, without authorizing Cell Split

2026-10-16 UTC. **DRAFT / SHADOW_ONLY / DENY_ALL**. This patch is an additive, isolated research qualification step on [PR #2364](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2364), exactly after the existing V21 committed base `910aabc24a77029f84e1c57d3e3f2aba42383a24`. Original V14–V21 source/receipts, model selections, Rust production owners, NDU, CAS/CNS, Final-use and `main` remain unchanged.

## Original blocking observation

The actual V21 `verify_cost_packet` checks a signed `latency_ns_samples` array of the correct length and independently recomputes p95/p99 and claimed CPU, energy and RSS. However, a cardinality-only latency stream **does not attach each time sample to a particular source case, model weight file, route, generation or fence**. The same 200 signed scalar values could be reordered across 200 source cases without changing the aggregate p99 or signature's internally asserted totals. A signature means that a key-holder signed these bytes, not that the OS collected them correctly.

V22 is a **supplemental source-first signed case ledger**, not a rewrite of V21's immutable prospective protocol or a new production database. It accepts the exact signed V18 source case roster, V20 saved-model executor roster, V21 meter packet, and a new meter-signed V22 request ledger. The V22 ledger's signature binds the V21 signed meter payload SHA, original V18 source SHA, original V20 executor SHA, run/boot, principal, purpose, generation and fence. Every source case must have **one record per arm** in stable canonical case-id order, matching the old signed raw latency array exactly. The candidate's actual `hard_route` must match the V20 executor packet for the same case. Model weights must equal the locked V21 no-change and candidate manifests. Requests before the frozen date or after the ledger seal are rejected.

The source roster must have the V21 minimum of 100 distinct **claimed** families per window and no family reuse between windows. This is not independent family custody: a single malicious operator could still fabricate different family identifiers, signatures, host names and both agreeing cost arrays. The genuine post-freeze corpus is **absent**. A diagnostic result is explicitly `CASE_LEVEL_SIGNATURE_AND_SAMPLE_PARITY_NOT_HOST_ATTESTATION`, with `scientific_promotion_authorized=false` and `production_authorized=false`. The source, executor, evaluator and meter keys are distinct byte strings but not externally enrolled independent institutions. The numerical model forward is *not rerun by V22 itself*; a caller must independently obtain and verify a V20 physical-model negative-only receipt. Raw stage totals remain meter claims, **not** kernel/hardware attested measurements.

## Original study and frozen reference

- V21 frozen protocol: `STEM_V21_FROZEN_PROSPECTIVE_PROTOCOL_20261016.json` unchanged, frozen commit `d80b7ba5593dbab8257a20f4a090d5c2e11f7f6e`, original AG News ZIP SHA `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`.
- V21 frozen prospective protocol SHA256: `31370cf349dcffc236c48ca7669ce77849ab080a7258b7a573504e7c5a41eaf3`.
- New V22 frozen supplemental protocol SHA256: `9fd2c9bf88d799f256d4eba625d9e8a79d6997c4ce1fbf5d3f878729e3ad933e`.
- Model weights, originating from V16 original-feature training: single Head `c63392b3...`, split `4dc71c47...`, gate `ac7e3f11...` (complete hashes in frozen protocol).
- No genuine new post-freeze source or target-host cost receipt has been supplied; `new_signed_source_families=0`, `qualified_future_windows=0`.

## Actually executed tests and evidence scope

Original archived mmBERT feature ZIP and authentic original research-saved V15/V16/V17 weights were provisioned to all prior tests that require them. The **combined V14–V22** suite, including original-weight V20/V21 model checks, executed **266/266 tests ordinarily** and **266/266 under `python -O`**, zero skips. The 25 added V22 tests use clearly **synthetic** signed 200-case panels generated with ephemeral test Ed25519 keys. Attacks include re-signed sample replacement, duplicate/reordered cases, modified principal/generation/fence/boot/run identity, invalid route, changed weight SHA, future and pre-freeze timestamps, duplicate families, substituted signer, forged V20 promotion, partial external packets, and boolean/integer alias. All 25/25 pass normally and 25/25 under `python -O`.

An important negative control deliberately re-signs BOTH the V21 meter values and the V22 per-case ledger with self-consistent but fictitious latency numbers. **It passes cryptographic consistency while still being explicitly rejected as an independent hardware attestation or scientific benefit.** That negative control is central to interpreting the output. It is not a real future experiment.

The V22 actual clock-based, no-new-source CLI was separately executed on the original frozen V20 `STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json`. The committed result `STEM_V22_NO_FUTURE_CASE_COST_HOLD_20261016.json` states `HOLD_MISSING_ORIGINAL_CASE_BOUND_HOST_EVIDENCE`, zero new sources, `DENY_ALL`. No original text, pretrained model weights, original task labels, user keys or detailed per-case latency traces were uploaded to the repo. CI only uploads this restricted HOLD receipt.

## Build and run

```bash
cd qualification/stem-cell-v1
python -m unittest -v test_v22_case_bound_cost_witness.SourceOnly
python -O -m unittest -v test_v22_case_bound_cost_witness.SourceOnly
python v22_case_bound_cost_witness.py \
  --protocol STEM_V22_FROZEN_CASE_COST_PROTOCOL_20261016.json \
  --v20-hold STEM_V20_ORIGINAL_SOURCE_HOLD_20261016.json \
  --out /private/new-v22-research-hold.json
```

The existing V14–V21 workflow adds V22 tests to its source-only PR path and a V22 create-only original-HOLD gate to the existing push path; **no new full-matrix workflow** was created. All YAML and inline Bash scripts parse locally. The exact new-HEAD hosted completion and global security/formatter/Cargo/Architecture runs still require independent terminal results; no predecessor green check is inherited.

## Unresolved acceptance

The next experiment requires actual 2026-10-17+ independently sourced original task families and true independent future windows; issuer/executor/evaluator/meter enrollment; original encoder **text → features** physical attribution; host-signed raw measurement backed by trusted OS/hardware and a durable replay frontier; independently reviewed old task retention; and full equal-lifecycle, 64/256/1024/4096 Cell target-host cost. Until that evidence exists, the correct decision remains **HOLD / NO MODEL SELECTION / NO TOOL EFFECT / NO MAIN MERGE / DENY_ALL**. Simply growing the Cell fleet, repeating previously exposed AG News calibration data, or counting distinct signer keys as independent institutions is not proof of general intelligence or giant-model equivalence.
