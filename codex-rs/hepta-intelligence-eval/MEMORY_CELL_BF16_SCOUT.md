# MemoryCell: real hosted CPU BF16 hardware scouting (2026-10-12)

## Why this is now the immediate experimental blocker

The pinned nine-arm research workflow cannot qualify on a GitHub runner without
accelerated BF16 CPU instructions. The [2026-10-12 run 38200169497](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38200169497)
passed the scoped source/format gate, but the actual reader machine identified
an **AMD EPYC 7763** without `avx512_bf16` or `amx_bf16`. The preserved
`host-qualification.json` reports `host_eligible=false` and **zero new
model calls**. Earlier actual-Qwen attempts on similarly underpowered CPU
hardware took about **922 seconds for one response**, above the frozen
180-second per-call research feasibility guard. These were hardware/resource
failures, not negative evidence of memory accuracy.

This repo also declares **trusted, manual-only** self-hosted runner availability
probes for `desktop`, `rog`, `pocket4` and `macbook-pro`. The desktop probe
historically completed in September 2026 and reported an RTX 4060; that
historic observation **does not** prove current runner availability, enough
GPU memory for the unchanged BF16/eager model, authorized access or sustained
model throughput. The manual `main`-ref / runner-group security boundaries are
not altered. **Do not automatically dispatch PR source to a personal machine.**

## This exact push-triggered experiment

`.github/workflows/hepta-memory-bf16-host-scout.yml` provisions three
**standard GitHub-hosted** Linux VMs, individually labeled `ubuntu-22.04`,
`ubuntu-24.04` and `ubuntu-26.04`. Each checks out the exact `github.sha`,
executes the existing pinned `strong_rag_host_gate.assess` and retains an
unsigned JSON receipt including the allocated CPU's feature intersection,
CPU-info digest, requested image label, original source commit and eligibility.
It runs model-free regression tests and uses no HuggingFace token or model
weights. The full raw `/proc/cpuinfo`, usernames, environment variables, secrets
and host identities are **not** uploaded.

A completed scout job means only that **a bounded CPU observation exists**.
It does not mean the old Qwen reader ran or the frozen outcome improved. Even
`host_eligible=true` is only ISA evidence for **that ephemeral VM**; a later
allocation on the same Ubuntu label may have different hardware. There is no
hardware reservation, measured decoder latency or independent semantic judge.
The reader itself keeps its separate source/model attestation, 180-second
feasibility threshold and independent replay.

If all three hosted images are ineligible, do not keep pushing unqualified
`ubuntu-latest` inference runs to get a green status. The remaining path is
an **explicitly authorized, trusted** BF16-capable CPU or BF16-capable GPU
runner with adequate memory, CUDA/torch support where applicable, a
fail-closed source-pinned test and a real 40-call calibration + 72-call
nine-arm Qwen evaluation. The existing CPU-only reference reader cannot be
silently moved to CUDA or exchanged for FP32/INT8; any GPU transport needs
its own reviewed exact-reader execution and runtime-parity receipt.

The research claims remain: `new_model_calls=0` in this scout;
`production_accepted=false`; parametric-memory gains, independently sampled
future-family superiority, human-reviewed sufficiency and semantic citation
precision are **not established**.
