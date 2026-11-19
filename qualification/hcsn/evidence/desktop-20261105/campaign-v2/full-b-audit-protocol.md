# External full-budget B CUDA audit v2

This is a prepared, independently reviewed diagnostic for the frozen execution
candidate. Preparation includes 25 synthetic admission and ownership controls;
it does not include a Torch numerical run, CUDA execution, a completed training
matrix, or a convergence result. The research package, original smoke evidence,
rematerialization module, parity checker and CUDA probes remain unchanged.

## UUID evidence correction

This version binds the corrected candidate source map
`415f6a2f2d7a89ad0585f29bea0d91928898a11ec8a672de39ce6e22f04d39e9`
and benchmark source hash
`7e89657ae4bd9444d0ed53b27cadaa70de1fa09027205cf2a0b8ca78891774bc`.
PyTorch 2.8's public CUDA UUID object stringifies as bare grouped hexadecimal;
physical GPU evidence uses a canonical `GPU-` prefix and lowercase hex. The
auditor reuses the pinned candidate's strict `canonical_gpu_uuid` helper, records
the raw hardware value, and checks that profile `gpu_uuid_raw` and canonical
`gpu_uuid` identify the same device. The benchmark, benchmark profile and current
launch profile must agree. Malformed, ordinal, partial, MIG and multiple-device
forms are rejected. Runtime profiles now use `hcsn-runtime-profile-v2`.

The actual nvidia-ml-py 13.610.43/device comparison accepted both bare and prefixed
UUID lookup and returned the same canonical UUID string. Therefore this fix does
not claim that the earlier NVML lookup necessarily failed. Canonical counter
keys, raw evidence and same-device readback are still required. Previously
observed physical power/energy `NOT_SUPPORTED` remains a separate limitation.
The v1 script, protocol, source and receipts are preserved unchanged.

## Input contract and launch gates

The immutable benchmark must contain all 170 unique terminal identities from
the original full configuration. The audit retains all 20 requested B identities:
two tasks, two population models and seeds 0 through 4. A failed or unavailable
training run remains an unavailable audit row. No unsuccessful identity is
dropped from the denominator.

The selected execution configuration must equal the original full JSON object
plus exactly `population_checkpoint_steps: 0` or `1` and
`cuda_memory_fraction: 0.5`. Original seeds, data splits, sequence length, hidden
size, batch size, learning rate and 400-update budget are unchanged. Both choices
are preregistered in `PROTOCOL.json`; the selected file's actual bytes are hashed.
The original full configuration and package's policy-1 configuration retain
their independently pinned byte hashes. An external policy-0 file need not have
the same whitespace as the policy-1 file.

The supervisor must enforce these gates before launching the full matrix and
this audit:

| Gate | Required receipt interpretation |
| --- | --- |
| Common | Reviewed frozen source and strict CPU suite passed; source/config/runtime identities remain bound throughout the campaign. |
| Policy 0 | Original full-shape B probe actually completed on the declared CUDA device/profile. The choice applies uniformly to all 20 B runs. |
| Policy 1 | Original full-shape B actually raised CUDA OOM; both fixed 16-case CPU and CUDA parity receipts passed; the fixed segment-1 candidate full-shape CUDA probe completed. |
| Audit input | Immutable full 170-identity terminal receipt, selected config, checkpoints, benchmark runtime profile and linking sidecar are available. |

The audit records this preregistered gate requirement; the supervisor owns the
gate receipt chain. A local admission control is never a substitute for a
strict CPU, parity, CUDA or full-budget gate. No audit inference counts toward
the 170 training runs, and no quality result selects the execution policy.

## CLI and packaging

Keep `PROTOCOL.json` beside the audit script. The script can be renamed to
`audit_full_population.py` without changing its bytes. All paths below are
examples; no scratch or desktop task path is embedded in the implementation.

```sh
CUBLAS_WORKSPACE_CONFIG=:4096:8 CUDA_VISIBLE_DEVICES=<actual-GPU-UUID> \
  python runtime_entry.py \
  --repo-root /path/to/frozen/candidate \
  --device cuda:0 \
  --profile /path/to/campaign/full-b-audit.runtime.json \
  --script /path/to/bundle/audit_full_population.py -- \
  --repo-root /path/to/frozen/candidate \
  --benchmark /path/to/campaign/full.json \
  --execution-config /path/to/campaign/execution.json \
  --runtime-profile /path/to/campaign/full.runtime.json \
  --benchmark-runtime-manifest /path/to/campaign/full.runtime-manifest.json \
  --launch-runtime-profile /path/to/campaign/full-b-audit.runtime.json \
  --launch-runtime-entry /path/to/bundle/runtime_entry.py \
  --output /path/to/campaign/full-b-audit.json
```

The four core arguments are `--repo-root`, `--benchmark`,
`--execution-config` and `--output`. The four profile arguments shown above are
used by the supervised campaign. A standalone fresh process can omit profile
arguments; the result explicitly records the absence of those provenance links.
An already imported Torch requires both launch arguments, a matching current
process ID, and the wrapper's two explicit import-order assertions.

`--runtime-profile` is the benchmark process's preprofile.
`--launch-runtime-profile` is this audit process's preprofile. They are separate
files from separate processes. Both use `hcsn-runtime-profile-v2`; the audit
checks device, physical UUID, driver, CUDA/Torch/Python versions, allocator
fraction, full installed-distribution map and its canonical hash, and all ten
flags specified in `PROTOCOL.json`. Actual values must match those profiles.

The launch profile must additionally match the entry file's byte SHA, current
script's byte SHA and resolved path, PID, and exact argument list after removing
one leading `--`. It must state
`launch_environment_validated_before_torch_import: true` and
`torch_preimported_before_entry: false`. The audit records `torch_preimported`
and both profile hashes. Evidence that the environment preceded Torch import
comes from the manifest-pinned wrapper's recorded assertion; the audit does not
claim to reconstruct import history independently.

The benchmark linking sidecar requires `benchmark_sha256` and
`runtime_profile_sha256`. If present, `execution_config_sha256`,
`source_sha256`, `source_map_sha256`, `software` and `torch_settings` must match
the selected inputs or actual runtime. The campaign supplies the selected config
hash and may include its admission, terminal-runtime and campaign-manifest hashes.
Those additional links remain available for the supervisor's evidence chain.

## Numerical protocol

| Joint factor | Bins | Internal time step | Inference batch | Test inputs |
| --- | --- | --- | --- | --- |
| 1 | 32 | 0.1 | 64 | All 1,024, original order |
| 2 | 64 | 0.05 | 8 | All 1,024, original order |
| 4 | 128 | 0.025 | 8 | All 1,024, original order |

The unchanged `audit_population.trace` helper runs directly on CUDA. The
original CPU three-grid auditor is never invoked. External inputs stay fixed
over each subdivided original time interval, effective refractory duration stays
0.3, and hidden traces are sampled at the original 64 input times. The
implementation class and checkpoint policy are verified against each original
run. Saved validation selection, exact identity, state keys/shapes/dtypes,
checkpoint hash, discretization and completed budget are checked before replay.

Factor 1 compares the entire hidden trace and final readout with the actual
encoder at zero relative and absolute tolerance. Predictions are computed from
`readout(sampled_hidden_trace[:, -1])`, matching the benchmark's time-slice
layout. The helper's original contiguous-final-state prediction is also retained
long enough to report its maximum absolute layout-related difference. This
separate descriptive quantity does not replace the exact benchmark comparison.

All predictions are reassembled into the original 64-example blocks before the
original FP32 CUDA squared-error sum and accumulation order. Factor-1 test MSE
must equal the saved GPU test MSE exactly. The factor-2 and factor-4 batches of
eight may change floating-point GEMM behavior; their numerical scope is explicit
and they cannot qualify a new training budget or supply a posthoc tolerance.

Each grid reports mass error, escape, minimum mass, test MSE, hidden-trace RMS
and final-prediction RMS relative to factor 1 and the preceding grid. RMS
differences accumulate on CPU in FP64. Hidden traces consume 16 MiB for each
stored grid; only factor 1 and factor 2 are retained, and factor 4 streams
against them. Extra per-chunk transfers and difference temporaries are separate
from this persistent-trace bound. Trace and prediction byte hashes are recorded.

There is no convergence pass threshold, retraining, parameter search, checkpoint
reselection, input subsampling or automatic smaller-batch fallback. The former
smoke audit's adverse evidence is unchanged.

## Timing, memory and physical energy

Each grid synchronizes before resetting CUDA peak statistics and synchronizes
again when closing its measurement interval, including failure paths. Absolute
allocated and reserved peaks include the resident model and allocator cache.
A failed reset never reuses an old peak; missing counters retain explicit nulls
and reasons. The allocator fraction of 0.5 is a process allocator policy, not an
exclusive physical-GPU reservation.

Grid wall time includes the trace, factor-1 exact encoder replay, transfers,
CPU differences, grouped MSE and progress I/O. Physical-counter readings cover
the corresponding observed device/package interval, without process-exclusive
attribution. A missing GPU energy counter remains missing, even if CPU package
energy is available. Incomplete intervals preserve actual partial readings and
are labelled incomplete. Runtime initialization, checkpoint loading,
between-grid checks and final publication are explicitly outside grid energy
measurement. Per-checkpoint and whole-audit wall times are separate fields.

Only measured stage times can establish practical runtime. The frozen helper
performs repeated mass/escape reads and transfers; this preparation makes no
ETA or efficiency claim.

## Output and failure contract

The final output is create-only. Its sibling `<output>.progress` directory
contains an exclusive `claim.json`, replaceable `progress.json`, and immutable
per-checkpoint receipts. File contents and relevant directory entries are
fsynced after publication. Existing final files or claims are refused; there is
no automatic resume or overwrite. Each per-checkpoint receipt is the row before
its own `progress_receipt` path/hash reference is added to the aggregate.

| Level | States and meaning |
| --- | --- |
| Final | `completed` only when all 20 B audits complete; `partial` retains some audited rows; `unavailable` retains all requested rows without available execution; `failed`, `invalidated`, or `interrupted` preserve failures. |
| Checkpoint | `audited`, `failed`, `unavailable`, or `interrupted`; the original benchmark status is retained when input validation reached it. |
| Grid | `completed`, `failed`, `unavailable`, or `interrupted`, with submitted/completed examples, original MSE blocks and actual cost fields. |
| Exit | 0 for completed; 2 for partial/unavailable or an existing-output CLI refusal; 1 for failed/invalidated/interrupted. |

`requested_b_runs` is always 20; `original_matrix_denominator` is always 170.
Source, config, profile, selected checkpoint and environment immutability are
checked around computation and at termination. The final all-checkpoint guard
covers the hash-verified checkpoint set, whose size is recorded separately from
all 20 requested identities. A provenance invalidation sets
`accepted_b_audits` to zero while preserving any historical row observations.
CUDA OOM, unrecoverable synchronization failure, invalidation and interruption
stop remaining computation and retain the remaining identities as unavailable.

## Preparation controls

```sh
python check_non_torch.py --repo-root /path/to/frozen/candidate \
  --output-dir /path/to/new-control-directory
```

The checker requires a new output directory and uses copied repositories. Its
children block actual Torch imports. Synthetic wrapper fixtures use an explicitly
labelled `ModuleType` placeholder solely to exercise preimport admission; they do
not imitate a successful GPU runtime or produce numerical results. Controls
cover both policies, full identity retention, input/protocol/profile drift,
raw/canonical UUID mismatch, rejected MIG and noncanonical identity fields,
checkpoint hashes and path confinement, launch PID/entry/arguments, immutable
output and concurrent owner claims. `negative-controls-v1/RESULT.json` records
25 passed, zero failed and an unchanged frozen candidate. The independent
static review is included separately. These results certify only these controls.
