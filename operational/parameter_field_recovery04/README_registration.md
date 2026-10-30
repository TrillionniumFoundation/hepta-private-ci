# Durable execution04 metadata registration and historical costs

These new operational modules leave the frozen scientific workers, public registration helpers, aggregate statistics, endpoint access rules and resource thresholds unchanged. Registration reads completed metadata and hashes artifact bytes; it does not train, score, activate a queue or publish an artifact. A failed or existing registration destination is preserved and is never retried automatically.

## Registration interface

Run from the restored Git checkout, after committing these modules and creating the explicitly pinned configuration:

```sh
python -B operational/parameter_field_recovery04/registration.py \
  --config /absolute/path/REGISTRATION_CONFIG.json \
  --expected-config-sha256 ACTUAL_CONFIG_SHA256 \
  --stage followups
```

Stages are `followups`, `endpoints`, `analysis`, and `finalizer`. The optional `--check-history-only` validates only available historical cost metadata; it does not register a stage, validate scientific completion or claim a new preflight PASS. A stage argument is still required. The driver uses a nonblocking `registrations/registration.lock`; the original helpers retain their own stage/controller locks and full validation.

The initial canonical queue has four jobs. `followups` emits eleven and `endpoints` emits fourteen. The fixed order is A-17, A-29, A-43, C, B-17, B-29, B-43, W, R-17, R-29, R-43, A_endpoint, B_endpoint, C_endpoint. Every original dependency is preserved, and each job after the first also requires its immediate predecessor. All previously accepted job dictionaries remain equal. New dependencies are supplied to the original helper's queue extension **before** it serializes any queue, freeze, bundle or cost receipt.

The driver emits canonical queues only. The external durable supervisor activates one next canonical job after its predecessor's successful completion and durable backup/readback ACK. It owns the actual queue, controller finalization, and subsequent analysis/finalizer execution. This module never changes the actual queue or reduces the original resource gates.

The final stdout line is one JSON object with schema `hepta.fullstudy.durable-registration-result.1`. It has `stage`, `bundle`, `canonical_queue`, `registration_cost`, `driver_receipt`, `driver_cost`, `files`, `historical_cost_projection`, `queue_activated: false`, and `workers_started: 0`. Every file descriptor is exactly `{path, bytes, sha256}` with an absolute canonical regular-file path. `files` maps each original BUNDLE payload name to a full descriptor; analysis includes `ANALYSIS_SOURCE_FREEZE.json` and `REPORT_INPUTS.json`, while finalizer includes `FINALIZER_SOURCE_FREEZE.json`.

Each stage directory also contains `DURABLE_REGISTRATION.json` and `DRIVER_COST.json`. The original `REGISTRATION_COST.json` is nested within the driver's measured interval and must not be added to it again. Supervisor inclusive child CPU overlaps the driver receipt and is another view, not another additive expense. Final receipt serialization is outside the driver's measured interval and is disclosed. A failing registration's partial files remain; the external supervisor must preserve its process exit and cost evidence.

Archive the complete stable stage directory, the history projection directory, the pinned configuration and source registrations. No helper-generated artifact is rewritten after sealing. The driver cannot include its own final receipt hash inside the same receipt; the external durable archive supplies that next binding layer.

## Configuration

The configuration schema is `hepta.fullstudy.durable-registration-config.1`. All descriptors below must already exist and their hashes must match. The explicitly supplied 40-character `source_commit` must contain the actual new driver/adapter bytes as well as the original sources required by each unchanged helper. No future or guessed commit is accepted.

| Field | Required value or meaning |
| --- | --- |
| `execution_episode` | `execution04_durable_20261030` |
| `source_root`, `source_git_root` | `/workspace/scratch/178ced6a501f/fullstudy_git` |
| `raw_root` | `/workspace/scratch/178ced6a501f/fullstudy_execution04_durable_raw` |
| `registrations_root` | `/workspace/scratch/178ced6a501f/fullstudy_execution04_ops/registrations` |
| `source_commit` | Actual full registered Git commit |
| `assets` | Existing absolute restored asset directory |
| `analysis_id` | Explicit alphanumeric identity, such as `analysis04durable` |
| `amendment`, `a_freeze`, `c_freeze`, `controller_freeze`, `initial_queue` | Descriptors of the prospectively registered new episode inputs |
| `historical_inputs` | Actual original REPORT_INPUTS_BLOCKED bytes; fixed SHA `2848a9fc4b3092b79c3bff158b4c966bce5941760c0ea531eb7b4cb45c31c785` |
| `driver_source`, `history_adapter_source` | Descriptors of these actual new module files |
| `helper_pins` | Descriptors keyed by `register_followups_v2.py`, `register_summary_v2.py`, `report_results.py`; their original hashes are also fixed in code |
| `history_mode` | Defaults to `strict_original_receipts`; alternate mode requires explicit `preregistered_public_summary_projection` |
| `history_receipt_relocations` | List of `{original_receipt, recovered_receipt}`; only identical bytes and SHA at the new path are permitted |
| `additional_failed_episodes` | Exactly two entries `{key, native_fact_receipt}`, keyed `episode02` and `episode03`; the legacy container name does not assert episode03 scientifically failed |

Explicit projection mode additionally requires `historical_summary`, the actual public ENGINEERING_SUMMARY descriptor, and `missing_preflight_receipts`, in original order. Each entry is `{original_receipt: ORIGINAL_MISSING_DESCRIPTOR, gradient_microsteps: 432}`. Both original descriptors and both public-summary counts must match exactly. A declared missing original path must remain unavailable; if original bytes become available, create an explicit revised strict registration instead of silently changing evidence modes.

The operational source freeze must include `registration.py` and `historical_costs.py`, plus the external wrappers that load them. Their descriptors are also bound as actual metadata. Include all other original helper source requirements unchanged. The original 26-seal aggregate and 30-seal finalizer population checks remain active.

## Historical evidence and accounting

Strict mode requires the actual bytes of both original preflight receipts. Projection mode does not invent replacements with `complete: true` or the original preflight schema. It writes a new `hepta.fullstudy.explicit-historical-cost-projection.1` containing explicitly cost-only rows, original unavailable descriptors, a public-summary binding and availability limitations. A selective JSON parser decodes only public-summary schema, source descriptors and gradient counts; unselected outcome numbers are skipped lexically and are not used in registration.

| Historical evidence | Known microstep lower bound | Availability and interpretation |
| --- | ---: | --- |
| Preserved original failure receipt | 102,320 | Original receipt bytes verified through the unchanged reader |
| Episode02 | 576 | New native fact record binds currently recovered partial-raw audit, failed monitor and preserved archive |
| Two original engineering preflights | 864 | Public summary supports two counts of 432; original RESULT byte streams are missing and cannot be reverified |
| Episode03 | 78,336 | New continuity observation records two previously observed completed A seeds; original execution receipts are unavailable now |
| Historical total lower bound | 182,096 | Additional unobserved work remains unknown; no new independent scientific samples are created |

Episode02 and episode03 remain distinct from the original failure receipt. The new native fact schema explicitly says it does not impersonate an original receipt. Episode03's later work, endpoint access, final execution status and whole-episode CPU remain unknown. Its inclusion in a compatibility `failed_attempts` output container is explicitly **not** evidence that the science failed.

The original historical V5 `FAIL` string is preserved exactly. New current-run training, reconstruction, witness and endpoint cost rows retain the original reader's construction. Public-summary 864 is excluded from `completed_receipt_gradient_microsteps`; it enters only the all-attempts lower bound. The historical total is added once, not once through each of its supporting documents. Peak RSS and overlapping inclusive CPU observations are not additive.

Missing old descriptors must not be embedded directly in new REPORT_INPUTS as if they were accessible artifacts: the original analysis validator recursively checks every `{path, bytes, sha256}` dictionary there. They instead live inside the explicitly bound projection file, whose own bytes and actual evidence bindings are verified. This preserves the original validator without pretending unavailable files exist.

## Analysis integration

The external analysis wrapper must retain original admission, source closure, worker supervision, completion sealing and report invocation. Within the real analysis child, scope the cost adapter around the unchanged analysis/report path:

```python
from operational.parameter_field_recovery04.historical_costs import apply_cost_adapter

with apply_cost_adapter(actual_report_inputs_descriptor):
    run_original_analysis_child()
```

The adapter verifies the bound configuration, projection, original historical manifest, actual support files and original report source. It scopes only `report_results.prior_costs`, `cost_rows`, and an appended rendering disclosure, then restores all original functions in `finally`. Nested use is refused. It never replaces the scientific assembler, statistical calculations, endpoint checks or current-run completion guards. Repeated reads return the same historical costs without mutating or growing the ledger.

## Bounded synthetic verification

```sh
python -B operational/parameter_field_recovery04/synthetic_test_registration.py
```

Eight synthetic checks cover canonical 4/11/14 extension and preserved job definitions; strict dependency rejection; default rejection of missing original preflights; exact summary counts and unique native episodes; lexical skipping of unused outcome numbers; one-time historical accounting; current-run cost rows equal to the original reader; and restoration on caller failure/nested-use rejection. Temporary fixtures are explicitly synthetic and removed afterwards.

On 2026-10-30, all eight passed, with no Torch/NumPy imports and zero science workers. Measured test interval: 0.0573042 s wall, 0.045388609 s CPU, peak RSS 21,954,560 bytes. An earlier test invocation rejected two byte-identical synthetic reference receipts; the fixture was corrected to include distinct synthetic IDs. No original source or real receipt was changed. These are metadata checks, not proof that any new scientific stage has run or completed.
