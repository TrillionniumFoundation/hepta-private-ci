# Neuron A0–A4: isolated sparse-state replacement qualification

Status: **shadow-only, no production authorization**. The source and tests in
this directory cannot show that a model has been deployed, trained, or outperformed
another model. V1 `SparseJournal` is unchanged and is the only durable legacy
replay contract. V2 is a pure multi-population mechanism, not a durable owner.
V3 adds an independent pure temporal candidate above V2, plus a separate
V3-only synced shadow journal. This is not the production Cell owner or
independent NDU authority.

## A0 — census the *actual deployed* Cell models

A source-tree fixture, metadata digest or synthetic timing is never accepted as
an active deployment. Export the active Cell registry from the target owner, and
export the exact selected manifest, trained weight blob, current committed
journal/checkpoint and runtime resource observation for **every** registered Cell.
Freeze an immutable snapshot and sign each evidence payload with an independently
provisioned operator Ed25519 key. Do not put the private key into this repository.

```text
secure-evidence/
  registry.json                  # signed authoritative Cell census
  cells/<cell_id>.json           # one signed payload per active Cell
  artifacts/<manifest>.json      # physically present selected manifest
  artifacts/<weights>.bin        # physically present selected weights
  artifacts/<checkpoint>.bin     # physically present journal/checkpoint
```

Each signed file has exactly `payload`, `signature_b64` and
`signer_key_id`. Sign `json.dumps(payload, sort_keys=True, separators=(',', ':'),
ensure_ascii=True, allow_nan=False).encode('utf-8')`; signer_key_id is SHA-256
of the Ed25519 public key's 32 raw bytes.

Registry payload:
```json
{
  "schema": "hepta.neuron.deployment-registry.a0.v1",
  "host_id": "<actual-host-identity>",
  "observed_at_utc": "<UTC ISO timestamp ending in Z>",
  "active_cells": [
    {"cell_id": "<id>", "generation": 1, "mechanism": "sparse-v1"}
  ]
}
```

Selected manifest blob:
```json
{
  "schema": "hepta.neuron.selected-model.a0.v1",
  "model_digest": "<64-lowercase-hex>",
  "mechanism": "sparse-v1",
  "generation": 1,
  "weights_sha256": "<64-lowercase-hex>",
  "weights_bytes": 123,
  "parameter_count": 456
}
```

The signed Cell payload carries exact copies of identity/generation/mechanism,
model digest, manifest/weight/checkpoint relative file paths and SHA-256 hashes,
weights_bytes, parameter_count, checkpoint_sequence, reopen_checkpoint_digest,
and `resource_receipt` with:
`measurement_kind=target-host-observed`, `host_profile_digest`,
`cpu_micros`, `peak_rss_bytes`, `p95_micros`, `p99_micros`,
`sample_count`, `replay_verified=true`. The keyholder must independently
validate that host receipts originated from actual model execution and reopened
the exact checkpoint; the audit script can validate the signed assertion but
**cannot substitute for a trusted target-host owner**.

```sh
python3 -m pip install 'cryptography==46.0.4'
python3 qualification/neuron-gated-sparse-v3/a0_deployment_evidence.py \
  --evidence-root /path/to/immutable/secure-evidence \
  --trusted-public-key /path/to/trusted-operator.pem \
  --expected-host-id "$HEPTA_HOST_ID" \
  --max-age-seconds 300 \
  --report /path/to/review/a0-audit.json
python3 -m unittest discover \
  -s qualification/neuron-gated-sparse-v3 -p 'test_*.py' -v
```

No actual deployment artifacts or signing keys are checked into this experiment.
The A0 command requires an independently determined target host identity and
enforces a fresh 300-second owner snapshot (configurable to no more than 24
hours). It rejects duplicate JSON keys, symlink or traversal paths, stale and
future-dated registries, wrong generations, fabricated host measurements, and
replay claims without attested checkpoint files. The owner must freeze a
read-only directory for the entire audit; file path checks alone do not defeat
malicious concurrent filesystem mutation. Passing cryptographic consistency
checks alone cannot prove that any trusted host actually executed a model.
Without host proof, **A0 = BLOCKED**, not passed. Every emitted report explicitly
sets `production_qualification=false`.

## A1 — V1 against V2 at the same *total* budget

On the same signed A0 model population, prepare immutable, preregistered
`(Cell, task, input_digest, temporal-window, label-availability)` pairs.
Freeze a no-change baseline and the model manifest before training, then use
identical raw feature streams and the same exact Encoder+preprocessor+tokenizer.
Count **all** trainable parameters, including V2 projection and any Head; budget
state bytes and projection edges as well as weights. The frozen **no-change**
baseline uses zero experimental optimizer steps. All *new* candidates share
the preregistered dataset digest and positive optimizer-step budget under
identical resource ceilings. Run V1 and V2 as
shadow mechanisms without invoking production routing. Only compare examples
with joined final labels, and never reuse future-window labels for training.

Report by task and time-window: task success, calibrated prediction scores where
applicable, Brier, ECE, OOD acceptance, future utility, negative transfer,
checkpoint/replay failures, CPU/RSS, p50/p95/p99 and sustained throughput.
Neither fixture output nor untrusted simulated timing can select the V2 arm.

`paired_shadow_analysis.py` accepts an evaluator-signed
`hepta.neuron.paired-shadow-evaluation.v1` envelope. Each joined case must
carry all arm outcomes for an identical input digest. Arm records must declare
the actual frozen artifact hash, shared Encoder, and counted total parameters
and state bytes. The top-level signed experiment separately registers
`training_dataset_digest` and `candidate_optimizer_steps` for all new
candidates while enforcing zero experimental steps on the no-change baseline. The
signed experiment binds registration, train cutoff, evaluation as-of dates,
distinct *claimed* Evaluator/Selector/Executor key IDs, and the A0 registry
hash. Distinct IDs are not proof of independent executor/selector ownership. It rejects
mixed budgets, future-window leakage, labels unavailable at evaluation time,
missing OOD cases and incomplete A4 scale coverage. Paired utility confidence
intervals aggregate by **Cell**, not by repeated events from the same Cell.
The unadjusted clustered t approximation is descriptive, not a causal NDU
proof. A4 additionally requires 64/256/1024/4096 size receipts claiming
real host measurement and binding execution/recovery receipt digests. The report intentionally always says
`NO_PRODUCTION_PROMOTION`, regardless of its paired metrics.

```sh
python3 qualification/neuron-gated-sparse-v3/paired_shadow_analysis.py \
  --signed-evaluation /path/to/evaluator-signed-shadow.json \
  --trusted-evaluator-public-key /path/to/independently-trusted-evaluator.pem \
  --report /path/to/review/paired-shadow-report.json
```

The contract and synthetic negative examples are tested in
`test_paired_shadow_analysis.py`. This evaluator signature alone cannot
authenticate target-host execution or make a causal NDU estimate. A4's
independent final-use evaluator, verified receipt provenance, calibrated
uncertainty and CAS proofs remain separate production blockers.

## A2 — Gated Sparse V3 temporal mechanism (in this PR)

`codex-rs/hepta-neuron/src/gated_sparse_v3.rs` contains a separate versioned
config, parameter digest, checkpoint digest and signal receipt. For each temporal
coordinate (all values signed Q24, with Q = 2^24):

```text
u = abs(input) / 8
v = abs(input - previous) / 16
g = clamp(b + w_input*u + w_change*v, 0, Q)
h_next = clamp((Q-g)*previous + g*input, -8Q, 8Q)
```

The divisions that normalize nonnegative magnitudes are integer floors;
**multiplication is signed nearest/ties-to-even**, the same rule as V2.
Gates and their normalization are frozen generation parameters. A0's real
weights must be selected and bound via Artifact CAS in later owner work.

For exact downstream parity, V3 feeds `h_next` into a private V2 tick with
temporary `temporal_decay_q24=0`. Inhibition, projection, per-population/global
Top-K tie rules, thresholds and eligibility remain V2's literal implementation.
The V3 config includes the full original V2 config digest and frozen gates;
the V3 checkpoint binds the original input bytes, predecessor and inner
V2 checkpoint with domain-separated V3 digests.

Unit tests exercise signed rounding, zero/full gates, deterministic tie/order,
scope/config/generation/clock/sequence fencing, corruption, and reconstruction
from 1–1024 original ticks. Separate `gated_journal_v3.rs` implements
the **shadow-only** `HPTNGV03` journal: bounded exact-tick frames,
checksum+digest replay validation, advisory locked owner file, synchronized
compare-and-append, duplicate retry, poisoned uncertain writes, independent
acknowledged-prefix anchor checks, and incomplete-tail recovery. Any reopen
of a nonempty journal **requires an independently retained anchor**.
The journal uses neither V1 wire bytes nor a V1 checkpoint; a V1 consumer
cannot interpret it as a V1 replay.

To avoid keeping full activation/gate history for thousands of Cells, the V3
journal retains only one 32-byte successor digest per Tick in its history
index. For a historical idempotent retry, the owner rereads and validates the
exact frame prefix, reconstructs the same signal receipt, and checks the
submitted input and predecessor. Corruption poisons that owner. This
exchanges bounded rare-retry work (at most 1,024 kernel replays) for
much lower long-lived in-memory journal history. The retained-index-size
accessor is a deterministic allocation **estimate**, not RSS; the real
checkpoint, Vec capacities, runtime worker, page cache and WAL still count
toward total resource envelopes. Capacity, complete-frame corruption and
historical retry tests are in `gated_journal_v3_tests.rs`.

The standalone `replay_gated_sparse_v3` is an in-memory reconstruction API,
not a journal. The new shadow journal is real file I/O at source level,
but still **not** a signed Artifact CAS, trusted witness implementation,
production owner, physical power-loss certification, target-host timing
attestation, or an authorized V1-to-V3 migration.

## A3 — frozen Encoder + equal-budget experimental candidates

Run this order, after A0/A1 and A2 evidence:

| Arm | Change relative to common feature input | Primary evaluation |
|---|---|---|
| V1 | Existing same-width sparse temporal decay | Frozen no-change baseline |
| V2 | Existing multi-population sparse kernel | Multi-population gain and stability |
| V3 | Input-dependent gated sparse temporal update | Memory retention and interference |
| Diagonal SSM | Stable, bounded per-channel transition with optional elapsed-time input | Long-range prediction / state retention |
| Low-rank minGRU | Input-conditioned update, factorized trainable projection | Complex temporal decisions at low parameter budgets |
| Sparse CfC | Bounded closed-form continuous-time update, recorded `delta_t` | Missing / irregular event timing |

Every candidate must use identical input information, training sets, split
boundaries, hyperparameter search budgets and total CPU/memory ceilings. Count
encoder reuse and cache invalidation costs in the whole-system budget. Avoid
claiming equivalent trainability merely because inference neuron widths match.
The first A3 arm now exists in `codex-rs/hepta-neuron/src/diagonal_ssm_shadow.rs`:
a stable per-channel Q24 diagonal recurrence with bounded `A^steps`, frozen
per-channel input gains and an explicit microsecond time quantum. The SSM
checkpoint uses its own digest domain and includes elapsed step count, original
input and predecessor. It delegates V2 sparse projections/competition unchanged.
Its tests check single- and multi-step transitions, time regression, 65,535-step
caps, Q24 signed ties-to-even, original input/generation drift, full V2 parity
at zero retention, saturation and deterministic cold replay. It is a **pure
shadow comparator only**, not a trained SSM or independent durable Cell owner.

Low-rank minGRU and Sparse CfC remain **planned, unimplemented and untrained**.
Neither the V3 nor SSM experiments have a real trained artifact or target-host
accuracy result. minGRU's parallel-scan training property does not
automatically apply to V3's state-dependent gate.

Research background: Feng et al., *Were RNNs All We Needed?* (2024),
https://arxiv.org/abs/2410.01201 ; Hasani et al., *Closed-form continuous-time
neural networks* (2022), https://doi.org/10.1038/s42256-022-00556-7 ;
Dao & Gu, *Transformers are SSMs* (2024),
https://proceedings.mlr.press/v235/dao24a.html .

## Separate four-arm native mechanism smoke (not A0–A4 success)

The `neuron_shadow_mechanism_probe` Rust binary executes the actual existing
V1, V2, gated V3 and diagonal SSM kernels on the same parsed, bounded Q24
trace. It runs **one arm per OS process** so process `VmHWM` peak RSS is not
contaminated by earlier arms. It records p50/p95/p99 tick nanoseconds and
microseconds, total elapsed time, throughput and final checkpoint frontier.
Unlike the signed A0 collector, the probe does not authenticate the input,
selected model, host or performance measurements.

The committed `fixture_q24_trace.json` has 32 temporal/activation channels,
8 synthetic monotonic events and a frozen feature digest. V2's per-population
local quotas differ meaningfully from the global V1 Top-K; the V3 and SSM
configurations remain **untrained fixture weights**. The 16-run sweep
covers V1/V2/V3/SSM × 64/256/1024/4096 Cells, with identical input data,
but is *not* a fair trained-model parameter-budget or target-host benchmark.

```sh
cd codex-rs
cargo test --locked -p codex-hepta-neuron --all-targets
cargo clippy --locked -p codex-hepta-neuron --all-targets -- -D warnings
cargo build --locked -p codex-hepta-neuron --bin neuron_shadow_mechanism_probe
python3 ../qualification/neuron-gated-sparse-v3/run_shadow_probe_matrix.py \
  --binary target/debug/neuron_shadow_mechanism_probe \
  --trace ../qualification/neuron-gated-sparse-v3/fixture_q24_trace.json \
  --report ../qualification/neuron-gated-sparse-v3/mechanism-only-results.json
cd ..
python3 qualification/neuron-gated-sparse-v3/q24_temporal_fuzz.py
python3 -m unittest discover \
  -s qualification/neuron-gated-sparse-v3 -p 'test_*.py' -v
```

The 4,096-step deterministic Q24 oracle in `q24_temporal_fuzz.py` was
also executed independently in Python, and Rust tests pin SHA-256 of the
per-event gate/temporal-state and SSM elapsed/retention/state streams. These
are exact fixed-point arithmetic conformance tests. Neither a pass nor a
speed result permits swapping the selected Cell. The matrix report always
asserts `target_host_qualified=false` and `ndu_eligible=false`.

## A4 — independent longitudinal NDU gate and promotion controls

The Evaluator must be separately owned from Selector and Executor. Freeze
no-change, pre-register held-out/OOD and chronological future windows, and
retain signed provenance for outcomes and resource samples. Report raw paired
sample count, effect size, confidence interval, negative-transfer distribution,
future-window retention, safety/OOD error, CPU/RSS and p95/p99 for 64, 256,
1,024 and 4,096 Cell target-host runs. Counterfactual comparisons must not
be confused with an observed split.

**No automatic promotion from these modules.** The experimental V3 journal
is not sufficient for the production owner. A versioned V3 Artifact CAS,
independent signed owner/witness composition and migration coordinator must
complete signature verification, exact
generation fence, shadow state migration, byte-for-byte V1 journal replay
regression, fault-injection recovery, rollback and independent NDU final-use
authorization. If any requirement is missing, retain the V1 production Cell.
