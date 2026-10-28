# V5 historical exact-regression diagnosis

## Status and scope

**The frozen historical exact-regression gate failed and remains failed. The underlying numerical cause is unresolved.** This document records a post-outcome, read-only diagnosis of existing V3/V5 artifacts. It neither replaces qualification nor introduces a tolerance.

The retained failure is `/workspace/scratch/e8a4dc33549f/v5_run/AUDIT.json`: `Ordinary48 historical endpoint regression failed`. The frozen auditor reaches this assertion after its trace/checkpoint/endpoint consistency checks, but it did not emit an overall success report. A separate strict within-run audit must state its own scope and preserve this failure.

No generator or observer was instantiated or called, no checkpoint was loaded, and no new holdout was accessed for this diagnosis. Source freeze, protocol and original failure were not changed. Exact input identities, array diagnostics and runtime observations are recorded in `HISTORICAL_REGRESSION_DIAGNOSIS.json`.

## Direct array findings

All deltas below are V5 minus V3. Both runs use the corresponding selected ordinary action (seed17: action2; seed29/43: action3), schedules6000–6003, and the same paired endpoint panel identities.

| Seed | Frozen task max absolute delta | Ordinary48 task max absolute delta | Ordinary48 task mean delta, reward | Ordinary48 clean mean delta, reward |
|---|---:|---:|---:|---:|
| 17 | 8.1434845922e-07 | 8.5681676865e-07 | -2.0936568041e-10 | +2.4156179270e-10 |
| 29 | 7.3909759513e-07 | 8.7693333628e-07 | -1.7862475956e-10 | +1.5284967959e-09 |
| 43 | 6.1020255093e-07 | 3.3698976041e-06 | -7.2189322965e-09 | +1.1216070561e-08 |

Every seed also has a frozen clean discrepancy. This establishes that an explanation requiring the new gate, eight-step transactions, or adapter checkpoint reloading cannot account for the entire failure: the untouched original models already fail exact replay.

The ordinary48 task counts of changed sample/schedule rows are:

| Seed | Schedule6000 | Schedule6001 | Schedule6002 | Schedule6003 |
|---|---:|---:|---:|---:|
| 17 | 17 | 15 | 14 | 19 |
| 29 | 17 | 192 | 21 | 17 |
| 43 | 1905 | 16 | 22 | 15 |

The largest discrepancy is seed43/schedule6000. Across all ordinary48 rows, the reward-observer drift and audit-observer drift differ by at most `2.220446049250313e-16`. This points investigation toward the parts shared by both scores—generated hard outputs, text and pixel-MSE—but does not prove which part changed. Small mean differences do not satisfy a registered exact-equality requirement.

## Identities and settings checked

The original model file hashes, parameter hashes, configurations and all pinned input file hashes match for every seed. The old and new panel identities also match, including ordered sources, public/target bytes, noise seeds and batch boundaries.

The current bytes of `learning.py`, `source_roles.py`, `adaptation.py`, `adapters.py`, `v6/neural.py`, `v6/conditioned.py`, `v6/data.py` and `v6/observer.py` match their old V3 development START identities.

Both recorded environments use Python3.12.14, NumPy2.3.5, Pillow12.3.0 and PyTorch2.8.0+cpu. Beyond version strings, the current SHA256 hashes of `libtorch_cpu.so`, `libc10.so`, `libtorch_python.so`, the Python `torch/_C` extension, and `libgomp.so.1` match the archived old runtime inventory.

The old `training_run.py` sets two Torch threads, one interop thread and deterministic algorithms before the whole development run, including endpoint scoring. The old independent hard-score audit likewise records two/one threads. V5 uses the same settings. The old `runtime_canonical_torch_threads=1` setting belongs to a separate runtime-control experiment; it is not evidence of different training-endpoint thread counts.

## Differences and unrecorded information

V3 scored each trained model immediately in the training process. V5 first sealed training and then scored reloaded adapter checkpoints in separate evaluation processes. That difference is relevant to investigation of learned paths, but cannot explain the frozen-original discrepancy by itself.

The current diagnostic process reports Intel Xeon Platinum8573C, AVX512, MKL2024.2 and MKLDNN3.7.1. The old artifact reports only `x86_64`, without CPU model or actual ISA dispatch. **CPU/ISA/backend differences remain a hypothesis, not an established cause.** Current diagnostic-process environment variables are not a recovered snapshot of either historical worker.

Local explicitly seeded generators create latent noise, and matching panel identities bind the noise seeds and batch boundaries. No source, schedule, batch or seed substitution was found.

The available Git evidence contains aggregate utility arrays and prior audit summaries. It does not contain the old per-row hard-pixel/caption bytes or selected ordinary adapter checkpoint bytes needed for a direct numerical localization. Checksums identify missing bytes; they do not reconstruct them.

## Minimum next diagnostic

Recover this one historical output, without rerunning a model:

- Archive member: `development/17/original-task.npz`.
- Original run location: `/tmp/hepta-field-v3-run/development/17/original-task.npz`.
- Required SHA256: `47ad388b03bf2109b01737107196019156c9f7cf0cebbbe71a92c060caa08c9e`.
- Recorded rows:2048.
- Hash source: V3 `evidence/INDEPENDENT_TRAINING_HARD_SCORE_AUDIT-development.json`, seed17, `files.original-task.npz`.
- New comparator: `/workspace/scratch/e8a4dc33549f/v5_run/evaluate/17/original-task.npz`.

First compare `pixels_u8`, `captions_utf8` and `output_sha256`; then compare `values_reward` and `values_audit`. If hard bytes differ, the discrepancy reaches generation/quantization. If hard bytes are identical, investigate the fixed-target pixel-MSE and scoring arithmetic from retained data. This first comparison requires no generator or observer call.

Potential explanations include small generator floating-point changes crossing uint8 quantization boundaries, shared pixel-MSE arithmetic drift, or small parameter changes on some learned paths. None is proven by the current evidence. Any subsequent execution experiment requires separate registration; it must retain the existing failure and cannot silently replace exact equality with an observed-data tolerance.

## Disposition

Keep the original `AUDIT.json` FAIL and all sealed outputs. This diagnosis does not authorize a fresh holdout, production integration, or a field-policy gain claim. A separately registered within-run audit can establish narrower internal consistency, while the historical exact-regression result remains failed.
