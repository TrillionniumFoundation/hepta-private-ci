# Exact Token Capture / Independent Re-encode Fence (research only)

**State:** Draft, no authority; branch stacked on #1987 (and therefore #1964 / #1963). No production Worker, Q24, NDU, CNS, final-use, CAS, WAL, Cell promotion or selected Encoder change.

## CI root cause and remediation

The existing real-Model workflow called the Producer with `--max-length 168 --encoder-batch 8` while the fresh independent Reviewer was called with `--max-length 128 --batch 8`. Since the full joint question/options/state is tokenized with `truncation=False`, the old commands could create *different* padded token matrices or reject before comparison. An apparently valid small Head safetensors checkpoint cannot fix incompatible input identity.

The workflow now freezes `TOKEN_CAPTURE_MAX_LENGTH=168` and `TOKEN_CAPTURE_BATCH=8` once for BOTH physical calls. No implicit shortening or fallback is permitted. Two original source groups of 64 rows each at 168×768 yield 8,257,536 float32 token elements per Cell, beneath the existing hard limit of 8,388,608.

The Producer embeds the observed `capture_profile` in its research report, without claiming an independent signature. The Reviewer requires this exact profile plus both Cell identities, 64 actual row attempts and completions per Cell, 64×max_length padded slots, zero incomplete module calls, and the correct bounded number of completed batches. **This gate runs before the independent model reload** to reject drift without wasting a real forward.

These *claimed counters* are not source attestation. The independent Reviewer still performs a fresh actual Encoder forward from original SHA-256-pinned weights/tokenizer/question/options, recreates frozen feature hashes, loads the twelve create-only safetensors, and replays numerical Head equations in NumPy. Only that combined route could establish retrospective numerical agreement.

## Verified in current local CPU environment

- Original inherited experiment suite: **104 passed** on PyTorch 2.10.0+cpu.
- New adversarial profile scenarios: mismatched 168/128, mismatched batch, Boolean/invalid numeric types, missing/duplicate/out-of-order Cells, forged padded-slot/forward counts and partial attempts.
- Complete local source-level suite after these changes: **124 passed**.
- The shadow-only shared workflow also includes the **two exact Prettier 3.5.3 quoting fixes** independently diagnosed in #1953; it does not waive the check.

This isolated local environment has no publisher ModernBERT tokenizer/weights installed. The new suite cannot independently prove that GitHub downloaded the model, completed either original pretrained forward, re-encoded in the second process, reproduced actual held-out quality, passed exact SHA hosted CI or met target-host throughput/p95/p99.

## Non-negotiable next evidence gates

1. Completed **exact PR HEAD** shadow/architecture/blocking CI receipts and actual hosted pretrained Producer/Reviewer logs. Queue and pending are not passes.
2. Complete original 128-row retrospective evidence and 12 saved trained Head checkpoints; independent numerical review of all 32 original holdout cases per seed, with explicit paired Pooled/Query accuracy/Brier/NLL and no post-hoc model winner selection.
3. Genuine no-change deployment baseline, independent prospective time-ordered source/outcome/NDU observations, negative transfer, calibration, OOD, security/resource budget and current revocation/final-use checks.
4. Independently signed Artifact CAS, native Q24 parity, physically shared Encoder Worker, real microbatch scheduling, generation fences, checkpoint WAL/recovery and repeated target-host 64/256/1024/4096 Cell performance.

**Research-only outputs always retain `production_admission=BLOCKED`, `selection_authorized=false`, `verified_prospective_future_NDU=false`.**
