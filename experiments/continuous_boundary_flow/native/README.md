# Continuous boundary native integration

This isolated Linux research host compiles unchanged Rust sources from repository
commit `5898cd8b0f724c3152b6cc52856721f72e5e08be`. It calls the original
`sparse_tick`, `AgentdNeuronOwner`, `NeuronRuntime`, inference-control receipt
adapter, journal, anchor witness and policy-bound NDU evaluator. It does not
replace those algorithms with Python approximations. Mathematical call/put,
margin and flow production can remain a separately versioned Python research
adapter; this is not a full native implementation of that mathematical cell.

## Frozen model contract

A profile defines 1–32 raw feature names, three explicitly typed continuous
channels, a bounded signed-Q24 affine encoder, the original sparse recurrence
parameters, and a three-row affine action head. The channel order after raw
features is `margin`, `risk`, `flow`. Risk is a probability in [0,1]; monetary
put values belong in an explicitly named raw feature. Independent profile masks
can remove each continuous channel before encoder execution. Inputs and
coefficients are bounded by 8 in magnitude; the original kernel's clipping,
top-k and homeostasis remain active. The exact profile bytes, source model,
objective and native binary identities are bound into receipts.

Action order is `keep`, `repair`, `stop`. The first two scores are calculated
from **actual native sparse activations**, not supplied Python action values.
Stop's reward is known to be zero in the registered task, so its head weights
and bias must be exactly zero. NDU consumes that stop candidate using its
required internal name `abstain`; the external task action remains `stop`.
The declared task tie rule is stop, then repair, then keep. NDU compares the
learned net action values. It does not fabricate action-specific tail estimates
or issue a probability/risk certificate. The fixed `risk_ceiling_q24 = 2^24`
field marks that no additional native risk ceiling is used in this profile.

`source_model_digest` binds the upstream mathematical-cell checkpoint, but the
host cannot authenticate a malicious upstream feature generator. The main
experiment must retain that checkpoint and causal feature-generation evidence.

## Two execution paths with different evidence scopes

`KernelReset` and `KernelAdvance` maintain bounded per-case state in one native
process. Each causal batch calls the original pure sparse kernel and original
NDU evaluator for every active row. The response exposes actual activations,
head scores, actions, temporal/checkpoint digests, mask identity and a receipt
digest. It explicitly says `durable_owner_execution=false`. Invalid batches
are checked before kernel work and never partially advance states. No future
observations are needed. `KernelBatch` separately evaluates complete supplied
sequences for numerical parity and training feature export.

`Open`, `Tick`, `Close` and `Resume` use the genuine long-lived Agentd owner,
model port, native runtime, original durable journal and anchor witness. Every
acknowledged tick appends a checkpoint-bound action receipt. A stop rejects
later unique observations; exact retries return the old acknowledgement without
another native transition. A new process can resume only after reconstructing
all numerical states and actions and matching the independent witness frontier.
Modified actions are rejected even if their untrusted receipt hash is updated.
Repair is a task action: the experiment environment performs its registered
physical reset, while the existing native recurrent checkpoint continues.
No hidden neuron reset or changed production checkpoint encoding is introduced.

The profile's calibration fields are a **research fixture for bounded encoder
domain validity**. The zero residual follows from predicting that same frozen
encoder output. It is not measured task-success calibration, confidence in
semantic quality, distribution-shift qualification, or permission for external
operations. Native authority remains `DENY_ALL` throughout. The explicit local
permit scopes output to the experiment directory and cannot grant production
or external effect authority.

## Python interface

Use `adapter.features` to create typed Q24 observations and `make_profile` to
encode frozen float matrices. `save_profile` writes immutable, content-addressed
JSON; the host checks its complete bytes before loading. All calls share one
`NativeBridge` process. Training can request `stage="transform"` so a zero head
does not end the stored sequence. Evaluation uses `stage="act"` and honors the
native selected action. Head updates require a different profile digest.

```python
bridge.load_profile(profile_path)
bridge.kernel_reset(profile_sha256, case_ids)
result = bridge.kernel_advance(profile_sha256, [
    {"case_id": case_id, "features": observation},
])
activation = result["rows"][0]["activation_q24"]
action = result["rows"][0]["readout"]["action"]
```

A durable run instead calls `bridge.open(case, seed, profile_sha256)`, then
`bridge.tick(observation)`. After closing the first process, a new bridge with
the same root and profile calls `open(..., resume=True)`. The case seed,
profile, binary, objective and complete checkpoint chain must still match.

## Build and verification

`build.py` copies pinned sources into a dedicated build tree and verifies every
external crate against the original repository lock. Generated build manifests
omit test-only dependencies and link the original NDU crate into the research
example; original Rust source bytes are unchanged. Those manifest differences
are recorded explicitly. This is not a full application or production build.
The `--reuse` path rechecks original source identities, retains previous build
logs and receipts, and rebuilds only the research wrapper as needed.

```sh
python -m experiments.continuous_boundary_flow.native.build \
  --repository /absolute/repository \
  --destination /absolute/isolated-build \
  --compiler /absolute/rust-toolchain/bin \
  --vendor-cache /absolute/verified-vendor-directory

python -m experiments.continuous_boundary_flow.native.test_native \
  --binary /absolute/isolated-build/target/release/examples/continuous_host \
  --output /absolute/new-native-validation
```

Behavioral tests cover all three channel interventions, causal batch/owner
parity, actual process restart and recovery, unknown profile/stale checkpoint,
malformed atomic batches, real stop cancellation, exact retry and action tamper
rejection. They are engineering checks, not evidence of learning superiority.

Cost receipts separate fresh kernel calls, original journal replay, independent
event-validation kernels, NDU calls, request/response bytes and native RPC time.
`total_native_kernel_calls` includes replay work. Per-process CPU and peak RSS
come from `wait4` for the exact child PID, avoiding double counting concurrent
bridges. Parent feature construction, JSON transport and training work remain
part of the encompassing experiment's accounting. CPU time and RSS are not
hardware energy measurements. Development failures remain in build/test logs;
new scientific runs must pin the final wrapper and binary before evaluation.
