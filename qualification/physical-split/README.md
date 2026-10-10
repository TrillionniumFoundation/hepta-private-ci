# Physical Cell Split qualification: evidence gate (not cutover)

This is a **fail-closed, independent evidence qualification** for the final
physical-split admission decision. It never executes Artifact CAS, migration,
CNS route changes, Supervisor fencing, or commits an execution ledger. It does
not grant any runtime authority. All five phases of production completion must
still pass separately.

## Evidence contract

A JSON manifest has these exact policy components:

- `schema`: `hepta.physical-split-qualification.v1`
- `dimensions`: an ordered JSON object of four named factors, each with two
  non-empty string levels. The gate verifies every unique element of the
  Cartesian product; the factor names and levels come from the frozen workload
  plan, **not from this script**.
- `frozen_workload_sha256`: lowercase 64-character SHA-256 digest; same for
  all 16 cases, and frozen before any measurement.
- `observer_id`: independent observer identity.
- `max_candidate_over_baseline`: one nonnegative bounded ratio (>= 1) per
  lower-is-better metric. A zero baseline requires a zero candidate value.
- `min_candidate_over_baseline`: one positive ratio per higher-is-better metric.
- `cases`: exactly 16 records, each containing only
  `{"evidence": ..., "signature_b64": ...}`.

Each case evidence contains `observer_id`, `executor_id`, `evaluator_id`,
`frozen_workload_sha256`, `factors`, `baseline_evidence_sha256`,
`candidate_evidence_sha256`, `baseline`, and `candidate`.
The three role identities must differ. Baseline and candidate evidence
digests must be distinct and nonzero lower-case hexadecimal SHA-256 strings.

Both metric maps must contain **exactly**:

`p50_ms, p95_ms, p99_ms, throughput_s, cpu_pct, rss_bytes,
communication_bytes, fsync_p99_ms, lock_wait_p99_ms, recovery_p99_ms,
long_term_negative_transfer, utility, future_window_retention`

All values must be nonnegative finite JSON numbers; throughput, utility and
future retention must be positive. Ratios in the frozen policy reject
regressions and require the specified retention/utility/throughput floors.

The independent observer signs each canonical UTF-8 JSON evidence payload
with Ed25519 (JSON sorted keys, no spaces, `ensure_ascii=False`). Its
signature is base64 encoded. The gate verifies using the explicitly pinned
public key and OpenSSL, rather than trusting a supplied `verified=true`
field. The host owner must independently establish that the observer key
belongs to the declared external observer and that sample provenance,
timebase, workload and run isolation are genuine. Cryptographic signature
verification alone **cannot** establish real workload execution or actual
fsync, lock, resource or migration measurements.

## Run

```sh
python3 scripts/hepta_physical_split_qualification.py \
  path/to/manifest.json \
  --pinned-observer-public-key path/to/externally-pinned-observer.pem \
  --pinned-policy-sha256 <sha256>
python3 -m unittest discover -s qualification/physical-split -p 'test_*.py'
```

Compute the pinned policy SHA-256 **outside the candidate host** over the
manifest object without the `cases` key, serialized as canonical UTF-8 JSON
(sorted keys, compact separators, `ensure_ascii=False`). Pin it before
executing the experiments. Do not read the pin from a field inside the
candidate-produced manifest. `openssl` must be installed; an unavailable
signature verifier makes qualification fail.

## Explicit non-claims

- Test fixtures are synthetic, not a substitute for independent target-host
  benchmarking, operational receipts or longitudinal negative-transfer data.
- This gate checks signed field-level measurement claims, not the attachment
  bytes identified by their SHA-256 digests. Archive and separately verify
  those raw observer artifacts with the same trusted observer.
- No topology/cutover authority is implied by a successful qualification.
  An independent final-use gate must additionally require verified production
  CAS, migration, child bootstrap, CNS cutover, Supervisor generation fence,
  a crash-recoverable ledger, and frozen NDU selection admission.
- No physical split may be enabled merely because this script exits zero.
