# Selected-checkpoint hardware measurement

This is a separate hardware probe of the frozen content study. It changes no model, training budget, data split, quality gate or checkpoint choice. `HARDWARE_DESIGN.json` fixes five architectures, two tasks, the first formal seed, three batch sizes and validation prefixes before any measurements. One checkpoint seed per architecture does not establish a population performance claim.

The harness requires the exact restored content evidence, externally pinned protocol and published archive-index SHA256 values, all archive member shards, frozen source dependencies, and the original content preflight receipt. Registration verifies checkpoint bytes and tensor hashes, the durable validation argmin, the development LR lock, study source/design and the original execution seal. Every selected state and companion record must also match the independently pinned published archive index, so editing a local checkpoint and its local hash together cannot pass. It then fsyncs a new immutable hardware protocol binding all inputs. Changes after registration are rejected.

```bash
python -m experiments.hcsn_blocker_closure_v1.hardware.preflight --output experiments/hcsn_blocker_closure_v1/hardware/PREFLIGHT.json
python -m experiments.hcsn_blocker_closure_v1.hardware.measure register --run-root <restored-content-root> --study-protocol-sha256 <independently-verified-protocol-sha256> --archive-index <published-INDEX.json> --archive-index-sha256 <independently-verified-index-sha256> --preflight experiments/hcsn_blocker_closure_v1/hardware/PREFLIGHT.json --output experiments/hcsn_blocker_closure_v1/hardware/results/attempt001
python -m experiments.hcsn_blocker_closure_v1.hardware.measure run --output experiments/hcsn_blocker_closure_v1/hardware/results/attempt001
```

Use a new attempt directory for any retry. A run never overwrites evidence. No GPU provisioning or package installation is performed. PyTorch 2.8.0 CPU or CUDA builds are accepted; the actual runtime, affinity, CPU quota and visible CUDA properties are recorded. The same frozen FP32 models run without compilation, autocast or TF32.

## Measurement scopes

Every forward starts fresh content/probability state and includes the entire sequence, within-sequence updates, reset and refractory behavior. Resident measurements keep model weights and inputs on the device. Host end-to-end measurements include fresh unpinned input/dt copies, complete inference, and a fresh full-output copy to CPU. Model loading, disk reads and CPU reference evaluation are separate setup costs. Reported throughput counts examples or input sequence steps, not inferred sparse events.

CUDA work is synchronized before and after each sample; CUDA events record default-stream elapsed time, alongside host wall and host CPU. Event elapsed time can include launch gaps. Both scopes must reproduce the selected CPU model within the registered FP32 tolerance. GPU failures remain failures; absence is recorded as unavailable. Quantiles are descriptive repeated timings on one machine, not independent machine replicates.

Energy is optional and uses the NVML C ABI directly. Only a full-GPU UUID matching PyTorch exactly is accepted. The total-energy counter is read in millijoules before and after a bounded active window; a positive monotone difference is converted to actual joules. Missing counters, MIG/unknown UUIDs, counter regressions, unresolved zero increments and short windows produce null joules. Idle counter windows are retained separately and never subtracted. The counter is device-wide, includes background/idle activity, and does not establish process exclusivity, CPU energy or whole-system energy. There is no MAC-based energy estimate.

Body clocks exclude imports/integrity checks. A caller needing whole-command accounting must wrap the process with an exclusive `wait4` receipt; body/setup/inference clocks are nested and must not be added to that receipt again.

## Primary API references

- [PyTorch 2.8 CUDA semantics](https://docs.pytorch.org/docs/2.8/notes/cuda.html): asynchronous execution, explicit synchronization and event timing.
- [PyTorch CUDA Event](https://docs.pytorch.org/docs/stable/generated/torch.cuda.streams.Event.html): event elapsed time is in milliseconds.
- [NVIDIA NVML device queries](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html): UUID identity and total device energy in millijoules since driver reload; unsupported devices can reject the counter.

The synthetic preflight checks fresh-state behavior, CPU timing/output consistency, binding/corruption rejection and pure energy-counter validation. It does not validate an unavailable CUDA path or claim real joule measurements.
