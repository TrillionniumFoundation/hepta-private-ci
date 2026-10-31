# Hosted trained-runtime audit

## Verdict and evidence boundary

The three declared runtime audits passed with the **same validation-selected trained checkpoint**. The stream recovered in a fresh Python interpreter, the actual native owner recovered its durable episode, and crossed interventions on a continuous value message changed actual KEEP/STOP actions while budget, fee, owner prefix and other message coordinates stayed fixed.

This is engineering execution evidence. It establishes neither task-optimal stopping nor a content-quality improvement from the stop policy. The neural kernel remains Python/PyTorch; the owner executing the decisions is the pinned Rust binary.

- Execution seal: 78b98ed8dd66294a3de6abce2fa0bbbd2c24f8d5.
- Immutable evidence commit: a0de582931981b3742433475ecf5565409854a5c.
- [GitHub Actions run 41059620366](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41059620366).
- Cohort gate: **70 valid jobs**, complete analysis, no analysis errors.
- This audit independently checked **70 conditions** across 15 immutable text files, recomputing fetched Git blob IDs, publication SHA256/byte matches, cross-file bindings, calibration extrema, causal comparisons, native recovery semantics and cost sums.
- It did **not** rerun a model or native binary, or decode the compressed archive's NPZ/journal payloads. The immutable archive preserves those payloads; exact-array assertions were executed by source-bound hosted code. [Publication](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/artifacts/hosted002/PUBLICATION.json); [archive member manifest](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/artifacts/hosted002/hosted_attempt.json).

## 1. Training and identity binding

The runtime checkpoint was fixed before formal training to fixed / selective_copy / hcsn_accelerated / seed 98031, rather than selected from test results or from the best task. The selected validation checkpoint is **step 32**, SHA256:

8679b9aecfe237055c449c92e46510b9832f8ccae03833a38657073c17ce665c

All three RESULT files, both recovery checkpoint manifests, causal protocol/calibration and the outer finalize receipt agree on this digest. The archive member for selected.npz has this digest and is **81,545 bytes**. The saved runtime weights.npz files also have exactly this digest. The selected model is width 32, depth 1, input dimension 64 and eight output classes, with the accelerated backend and the stable probability profile. [Binding plan](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/EXECUTION_BINDING_PLAN.json); [actual binding](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/hosted_finalize001/CHECKPOINT_BINDING.json); [finalize](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/hosted_finalize001/RUNNER_FINALIZE_RESULT.json).

The actual hosted environment recorded Python 3.12.14, Torch 2.8.0+cpu, NumPy 2.3.5 and SciPy 1.17.0. It exposed a private cgroup view (0::/), memory.max=8589934592, memory.swap.max=0, and cpu.max=200000 100000. OOM and OOM-kill counters were zero at the recorded finalize identity check. Container userland was Debian 13/trixie on the Ubuntu 24.04 host kernel. The image digest is bound by public plan/workflow, without claiming independent inside-container image attestation. All 93 runtime source-map entries agree with the frozen 124-file execution map. [Public identity](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/hosted_finalize001/PUBLIC_IDENTITY.json).

## 2. Stream and cross-process recovery

The predefined unlabeled panel used batch 2, length 128 and a recovery cut after observation 37. Results were:

| Check | Observed result |
|---|---:|
| Batched versus streaming maximum logit difference | 4.32133674622e-07 |
| Allowed absolute difference | 0.0001 |
| Argmax disagreements | 0 |
| Suffix logits after fresh-interpreter recovery | Bitwise equal |
| Final numeric state after recovery | Bitwise equal |
| Persistent numeric state | 968 bytes at every observation |
| Maximum probability mass defect | 4.65661287308e-08 |
| Maximum normalization L1 correction | 5.58560714126e-07 |
| Midpoint maximum refractory occupancy | 0.157351896167 |

The archive manifest gives identical SHA256 for expected and recovered state NPZ files, and separately for expected and recovered suffix logits. The fresh interpreter verifies saved input/source hashes before restoring the model and state. The 968-byte figure covers elapsed time, content, probability and boundary arrays; it excludes weights, optimizer state, history and backpropagation storage. [Stream result](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/trained_stream001/RESULT.json); [recovery contract](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/trained_stream001/CHECKPOINT.json).

## 3. Actual native recovery and STOP semantics

Three actual pinned native processes executed the complete episode and the independently restarted prefix/suffix. The logical episode made six neural reads and produced **KEEP, KEEP, KEEP, KEEP, KEEP, STOP**. The replayed prefix was three observations, followed by three suffix observations in the fresh Python/native path.

The audit independently compared full versus prefix+suffix signals, logits, actions, before/after owner checkpoint hashes, event digests, input-feature digests, activation/eligibility vectors and readout objects. They agree. The executed checker also reports bitwise final neural-state equality. The native recovery counters record three original journal replay steps. [Native result](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/trained_native001/RESULT.json); [native checkpoint contract](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/trained_native001/CHECKPOINT.json).

Both terminal paths rejected subsequent native ticks, and the Python read guard made **zero** further neural calls after STOP. All seven native processes across recovery and causal audits passed duplicate-event idempotency: a duplicate did not execute another native transition or model/NDU call. Four native_errors counters are the four deliberately requested terminal rejection probes, with successful process exits and unchanged terminal state; they are not four unexplained execution failures.

The recovery episode intentionally changes its external engineering budget from +1 to -1 at read six. Its action sequence alone therefore does not isolate neural-value causality; that issue is tested separately below.

## 4. Continuous value-to-action causality

The predeclared calibration used 32 unlabeled fixed-seed inputs (seed 730017). It selected the first minimum and maximum of actual model mean(J-G), at indices **2** and **31**, and fixed the midpoint threshold to **0.745678007603**.

The continuous owner coordinate was:

**continuation = 0.05 + 0.9 × tanh(sent_value - fixed_threshold)**

All four cases used the same native binary/profile, weights, native prefix/checkpoint, external budget 0, read fee 0, context and other three zero-valued message slots. Only the continuation coordinate changed. The natural states were replayed from the saved trained weights and panel; their values, logits and numeric-state hashes matched the calibration records exactly. [Protocol](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/trained_native_causal001/PROTOCOL.json); [calibration](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/trained_native_causal001/CALIBRATION.json).

| Case | Actual neural J-G | Sent J-G | Continuation message | Actual owner action |
|---|---:|---:|---:|---|
| natural_low | 0.545350432396 | 0.545350432396 | -0.127921102343 | STOP |
| natural_high | 0.946005582809 | 0.946005582809 | 0.227921102343 | KEEP |
| high_state_frozen_low_value | 0.946005582809 | 0.545350432396 | -0.127921102343 | STOP |
| low_state_counterfactual_high_value | 0.545350432396 | 0.946005582809 | 0.227921102343 | KEEP |

The high state and its frozen-low-message counterpart have identical actual neural values, logits and state hash, yet KEEP changes to STOP. The low state and its high-message counterpart also share the actual state, while STOP changes to KEEP. Thus the observed action follows the intervened continuous value message rather than the budget schedule. Each message is **2,985,021 Q24 units** from the native threshold, exceeding the declared 16-unit separation guard. [Causal result](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/trained_native_causal001/RESULT.json).

The midpoint and extrema deliberately ensure engineering coverage on this same unlabeled panel. This is not heldout policy evaluation, task-utility training, or a demonstration that the chosen threshold is optimal. The native owner's effective_action/readout.action supplies the STOP evidence; a raw NDU frontier marked abstain is not relabeled as a different raw NDU stop primitive.

## 5. Reset and refractory state are part of the executed model

The source-bound model retains eight active finite-volume cells and two Erlang refractory phases per physical channel, across eight channels. Exit flux enters the first refractory phase. Phase evolution then returns probability through reset_weights; the accelerated kernel explicitly includes that transition. Model.advance propagates this entire probability vector, and the vector plus physical parameters enters the content gate.

Observed refractory occupancy was positive at the streaming midpoint, and at every native read. Native read occupancies were:

0.000156193, 0.002286018, 0.010507377, 0.014760802, 0.031198781, 0.060939677

The phase state is serialized and recovered with the complete neural state. This rules out describing refractory state as an unused diagnostic field in this execution path. However, these receipts do not separately report phase-to-reset flux or a reset-off/refractory-off intervention on the trained panel; they do not isolate a reset-specific accuracy or utility benefit.

The native message field named risk is **current refractory occupancy**, not first-hit default probability. Expected event activity is passed through -expm1(-activity). The neural physical interval uses scale 0.1, while the owner's paid READ clock is an observation index. Native STOP terminates the external read loop; it is not the neuron's regenerative reset.

[Probability propagation source](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/78b98ed8dd66294a3de6abce2fa0bbbd2c24f8d5/experiments/hcsn_conservative_acceleration_v1/model.py), [accelerated generator source](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/78b98ed8dd66294a3de6abce2fa0bbbd2c24f8d5/experiments/hcsn_conservative_acceleration_v1/kernel.py), and [regenerative reference source](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/78b98ed8dd66294a3de6abce2fa0bbbd2c24f8d5/experiments/hcsn_distributional_v2/distribution_kernel.py) were compared against the execution source map.

## 6. Complete cost coverage and scope

| Complete outer worker | CPU seconds | Wall seconds | Peak RSS, MiB |
|---|---:|---:|---:|
| trained_stream001 | 4.834384 | 4.836009 | 277.348 |
| trained_native001 | 3.927266 | 3.940738 | 264.477 |
| trained_native_causal001 | 2.394689 | 2.406827 | 264.926 |

The three complete runtime workers cost **11.156339 CPU seconds**. Their outer wait4 measurements already include Python imports, calibration, neural replay, serialization, fresh-interpreter resume and waited native descendants.

The entire finalize stage includes analysis, native restoration and Git/source validation: **14.993787 child CPU seconds**, plus **0.117646284 coordinator CPU seconds**, for **15.111433284 CPU seconds** over **15.137225781 wall seconds**. The coordinator clock begins at RunBook creation and does not claim to cover imports before that point. [Full finalize accounting](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/a0de582931981b3742433475ecf5565409854a5c/experiments/hcsn_conservative_acceleration_v1/results/hosted_finalize001/RUNNER_FINALIZE_RESULT.json).

The seven actual native children account for **0.029175 CPU seconds** as nested detail; this number is **already included** in outer worker costs and is not added again. Their owner counters record 20 fresh owner ticks; native owner actual_model_calls/actual_kernel_calls are not PyTorch HCSN calls. The causal worker separately executes 32 calibration neural steps plus 70 exact replay steps.

This audit supports a functioning Python/PyTorch neural kernel with a real pinned Rust owner. It does not establish a native neural-operator implementation, energy savings, GPU throughput, a multimodal foundation-model result, or task-optimal stopping. Whole-workflow provisioning and dependency-install CPU are not included in the measured runtime costs. Failed local and first-hosted attempts remain separately recorded rather than being relabeled as part of this successful run.

## Machine-readable audit

[HOSTED_RUNTIME_AUDIT.json](HOSTED_RUNTIME_AUDIT.json) contains all recomputed checks, file SHA256/Git identities, checkpoint binding, causal case values, costs, archive coverage and limitations. Full raw evidence is preserved in the immutable archive; this audit did not repeat archive extraction.
