# HCSN gated CUDA campaign bundle v1

This bundle prepares the fixed 170-run experiment and its diagnostics. At bundle
preparation there are zero completed CUDA results in this package, physical GPU
energy availability remains unknown, and CI and research qualification remain
open. Runtime receipts, partial work and later results must be published as
independent evidence; the controller does not push commits or change runners.

## Frozen research identity

- Original baseline commit: `28a61d14ea7d4c3b3c515ab57b29c98de22e5673`.
- Execution candidate commit: `fe1def4a8a6655a361726f3ca275d9f5688dd394`.
- Candidate source map: `1c49f03c3525adde66be08a6be0779dccb2ed803c497bf74daba66ad6e5c2087`.
- Candidate benchmark source hash: `abff34d45fe5829f59c28fc324e6a5c25dc5c04e533ae52b8d2048740ac1e72a`.
- Original full configuration bytes: `7fa3d05b8c04a918043afdfa1c266a17beccb814351258d0555a753baf13777a`.

The original 17 models, five seeds and two tasks retain all 170 identities. Each
completed run requires 400 updates, batch 64, sequence length 64, hidden size 64,
25,600 training examples and 1,638,400 tokens. All original data, validation
selection, optimizer and training fields are unchanged. Source and tests remain
fixed throughout execution.

Policy 0 uses the original population encoder if its real full-shape CUDA probe
succeeds. Policy 1 uses the frozen segment-1 rematerialized encoder only after a
real original-B graph OOM, both complete 16-case CPU/CUDA parity receipts and
successful full-shape candidate probes. The selected policy applies uniformly
to all 20 B identities and never depends on held-out quality. The only added
execution config fields are `population_checkpoint_steps: 0|1` and
`cuda_memory_fraction: 0.5`.

## Ordered gate chain

1. Verify this manifest, all bundled files, ten existing task-relative tools and
   evidence inputs, original baseline source/full-config pins, and candidate
   source/full-config pins. Require at least 5 GiB free on the task volume.
2. Wait at most 24 hours for the pinned Torch and Mamba READY receipts. The
   controller installs no packages. It then obtains the environment's shared
   installation lock, reverifies READY and starts sequential research stages.
3. Run strict baseline CPU checks (95/95) and candidate CPU checks (104/104), with
   Torch required and zero skipped tests.
4. Run original A and original B complete-shape CUDA one-update probes. For
   an original-B OOM, run fixed CPU parity, fixed CUDA parity, and both B-model
   candidate complete-shape probes before allowing policy 1.
5. Run the original Mamba-2 complete-shape CUDA probe. Write the immutable
   selected execution config and admission receipt linking the actual gates.
6. Run the existing smoke separable audit as its own CPU diagnostic. Its outcome
   cannot select a model or an execution policy.
7. Run the full immutable 170-identity matrix. Preserve all terminal identities,
   failed/unavailable outcomes, partial attempt costs and checkpoint bytes.
8. Link the raw benchmark receipt to its runtime profile and run the external
   full-B CUDA audit over all 20 requested B identities. Factor 1 retains batch
   64 and exact same-device replay; factors 2/4 use preregistered inference batch
   8 and regroup predictions in original blocks of 64. No convergence threshold
   or training credit is assigned to this diagnostic.

Every research child records the fixed FP32 runtime: physical GPU UUID,
driver/software versions, allocator cap, `CUBLAS_WORKSPACE_CONFIG=:4096:8`,
highest matmul precision, TF32 disabled and declared determinism settings.
The full-B audit separately binds the benchmark profile and its own current
process launch profile. A runtime or source change blocks the campaign.

## Ownership, cost and failure behavior

`envsetup/campaign.lock` is an exclusive lock for this task's campaign. During
experiments, `envsetup/install.lock` is held shared; compatible installers use
it exclusively. Owned children inherit both lock descriptors. These locks do
not reserve the whole computer or provide exclusive GPU access. The allocator
cap is a per-process policy, not a physical-memory reservation.

Stages run sequentially. Initial ownership, profiles, stage launch/finish
receipts, terminal results and checkpoint evidence use unique/create-only paths.
Progress snapshots are separate. The controller records each owned child's PID
and process group and stops only that child group on interruption or failure.
It does not retry failed training automatically, reduce budgets or reuse an
existing campaign output directory. The 24-hour deadline applies to waiting for
runtime readiness, not an asserted training ETA.

Allocated/reserved peaks and physical-counter readings are measured when
available. Missing physical energy is never replaced with zero. Partial
intervals and incomplete attempts retain their actual costs and missing-data
status. Completion of training or replay alone does not establish physical
energy completeness, resolution independence, task superiority or GitHub CI.

## Layout and invocation

The archive has one top-level `campaign-bundle-v1/` directory. It contains the
three frozen gate files, fixed external audit and protocol, this README, the
manifest, and exactly the 32 candidate package files. There are no caches,
training outputs, synthetic fixtures or installer artifacts in the bundle.
The original package stays at the task root; no new Python files are added to
it. `task_files_sha256` names existing task-root dependencies, not bundled files.

```sh
python /path/to/campaign-bundle-v1/campaign.py \
  --task-root /data/hcsn-cuda-170run-20261105-r1 \
  --output-dir /data/hcsn-cuda-170run-20261105-r1/campaigns/<unique-campaign-id> \
  --manifest-sha256 <SHA256-of-this-bundle-MANIFEST.json> \
  --runtime-wait-seconds 86400
```

`MANIFEST.json` binds every runtime file except itself; the independently recorded
manifest SHA binds the manifest. The original 23-file Python source map and
original full config are checked separately by the controller. The accompanying
ZIP inventory records all paths, fixed timestamps, file modes, lengths and hashes.
Synthetic controls and static review reports are retained separately under
`publication-evidence/`; they are preparation evidence, not CUDA pass receipts.
