# C2: four bounded cold resumes of surviving checkpoints

The new diagnostic completed **four real optimizer calls**: two independent cold restores of each surviving `hcsn-s211-lr0.001` and `hcsn-s307-lr0.001` checkpoint. Both pairs produce exactly equal saved tensor states, gradient hashes and metrics. An independent archive reader verifies the original/restored model, AdamW and RNG states directly and checks all saved after-update tensors.

This establishes bounded cold-resume integrity for these two checkpoints and their next effective training batch. **The original controller remains `UNKNOWN`; complete six-fit training replays remain 0/6; scientific admission remains `HOLD`.** No new convergence, validation/test quality, original-runtime reproduction or full-campaign completion is asserted.

## Frozen experiment identity

`REQUEST.json`, `SOURCE_EXPECTATIONS.json` and `runner.py` are bound by `FREEZE.json` under identity `hcsn-c2-cold-resume-20261119-d741-001`. The executed source retains the original v8 localization task, prepared-data manifest, actual first batch after each surviving epoch and original model/optimizer construction. The prepared population is `all-development`; confirmation access is false. Every referenced source and episode digest is checked before numerical work.

| Input fit | Complete epoch restored | Next logical update | Effective batch | Loss | Gradient norm before clipping |
| --- | ---: | ---: | --- | ---: | ---: |
| `hcsn-s211-lr0.001` | 126 | 1513 | 32 episodes, 4 micro-forwards, 8,089 events | 1.1775529477712174 | 0.5310263703750616 |
| `hcsn-s307-lr0.001` | 127 | 1525 | 32 episodes, 4 micro-forwards, 7,995 events | 1.0714215312041069 | 0.5420318692017909 |

Each row was independently restored and executed twice in fresh child processes. All four loss, gradient-norm, event-count and micro-forward-count differences from the corresponding surviving original journal entry are exactly zero. These are training-batch observations, not held-out evaluation scores.

The two original input checkpoint SHA256 values are:

- Seed 211: `e98973d5d41621727444a2c117b89a7f33925b96066f092136c2f945b1453da3`.
- Seed 307: `032d43dc0e6f20a6d4113102ae32faa57809c714875beec4ab2ab76358e93441`.

## What was checked

The runner restores the full model state, construction configuration, AdamW state/groups, Torch RNG and episode-order RNG. It serializes and reloads the restored state before running the original effective-batch backward routine. Connected finite gradients, clipping, an actual optimizer step, nonzero trainable-parameter changes and unchanged frozen physical/shared state are checked. Every AdamW step counter advances once.

The after-update checkpoint preserves the last complete epoch and adds an explicit **mid-epoch continuation cursor**: the current shuffled episode order, episode identifiers, completed effective batches, next episode offset and `complete_epoch=false`. One batch is not represented as a complete epoch.

`audit.py` reads the exact archived original, restored and after-update checkpoints with `weights_only=True`. It checks tensor dtype, shape and contiguous bytes, full optimizer state, RNG progression, cursor semantics, actual parameter deltas, finite saved optimizer tensors, original-journal metrics and per-PID resource receipts. It compares both replicas' saved states and their instrumented gradient hashes. It makes **zero forward calls and zero optimizer calls**. It does not independently regenerate backward gradients; that limitation is retained in its report.

## Measured execution cost and bounded scope

The frozen limits are one child at a time, one numerical thread, one optimizer update per child, 300 seconds per child, 1,260 seconds for the parent, an 8 GiB address-space limit and a 6 GiB peak-RSS stop threshold.

| Child | Wall seconds | User CPU seconds | System CPU seconds | Peak RSS bytes | Exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Seed 211, replica 1 | 65.505322 | 58.026767 | 6.997833 | 3,222,208,512 | 0 |
| Seed 211, replica 2 | 65.205096 | 58.336879 | 6.657982 | 3,272,966,144 | 0 |
| Seed 307, replica 1 | 57.493265 | 51.422677 | 5.912418 | 3,205,382,144 | 0 |
| Seed 307, replica 2 | 58.492625 | 51.820927 | 6.024014 | 3,210,440,704 | 0 |

These are exact child `wait4` receipts through process exit. Child wall time sums to **246.696308 seconds**, and user plus system CPU time sums to **245.199497 seconds**. Runtime preparation, archival, independent reading and historical original training are separate costs. All four child processes finish within their frozen limits. Native execution job `1a1f269c02a-ffbe-b12` and archival job `1a1f26e689d-ffbe-b1d` both have authoritative successful, complete, non-timeout terminal receipts.

## Runtime preparation and retained failures

The former runtime metadata describes Torch `2.8.0+cu128`, but observation found an incomplete/nonfunctional import. It was not silently repaired or relabeled as an exact replay. This diagnostic uses a new Python **3.12.3**, Torch **2.8.0+cpu**, NumPy **2.3.5** runtime, with package record identities retained in the artifact.

Three unsuccessful preparation attempts remain in this directory:

| Preparation job | Terminal outcome | Evidence |
| --- | --- | --- |
| `1a1f24892ee-ffbe-aba` | Timeout, exit 124 | `RUNTIME_INSTALL_TIMEOUT.json`, original stdout gzip |
| `1a1f253ff32-ffbe-adc` | Range download read timeout, exit 1 | `RUNTIME_RANGE_FAILURE.json`, stdout and stderr |
| `1a1f25ec4c6-ffbe-af9` | Missing-range read timeout, exit 1 | `RUNTIME_MISSING_RANGES_FAILURE.json`, stdout and stderr |

The final transferred range was 2,097,152 bytes, SHA256 `acc26c109fbf938298fce2c6cc0dccc87687174018eef5b93f1be4a4a93a60f0`. The complete 183,914,597-byte official CPU wheel was accepted only after matching the official SHA256 `cb9a8ba8137ab24e36bf1742cb79a1294bd374db570f09fc15a5e1318160db4e`. Preparation job `1a1f2651f0b-ffbe-b0a` then completed successfully. The failed preparation attempts made no checkpoint or optimizer calls and remain separate from the four successful diagnostic calls.

## Exact evidence and independent review

The exact ZIP is `evidence/c2-cold-resume-exact-artifact.zip`: **4,153,098 bytes**, SHA256 **`04b96233a5421433b8ef9fe1d8e019ba28721fc1543d187591a742ee4bc55261`**. It contains 41 manifest-bound members plus `MANIFEST.json`: frozen executed source, runtime metadata, both original checkpoints, original epoch commits/plans, all restored/after-update checkpoints, journals, result JSON and child cost/stdout/stderr files.

The download used 64 version-pinned chunks of at most 64 KiB. Each chunk SHA256 and the assembled full SHA256 were verified. `evidence/DOWNLOAD.json` retains the exact version, offsets and hashes; `ARTIFACT.json` is the original receipt. `evidence/readable/` contains 31 unmodified small JSON/JSONL/stdout/stderr members, with extraction identities in `EXTRACTION.json`. Binary checkpoints remain in the exact ZIP.

`evidence/INDEPENDENT_REVIEW.json` reports `VERIFIED_BOUNDED_COLD_RESUME`, four completed optimizer events and two exact cold-repeat state comparisons. The independent local reader used the shared CPU runtime solely to deserialize and compare saved data; it did not rerun a model. Original journal archive SHA256 `7f2001bcc178e78c5f8de120007110e93534ba5a19e490fff307065e5466d2c3` is checked before comparisons.

To repeat the read-only archive audit from the repository root with PyTorch installed:

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  python qualification/hcsn_c2_cold_resume_20261119/audit.py
```

The executed runner is bound to the recorded original host paths and immutable inputs; the reader works on the retained repository archives. No CI workflow is added or modified. The proposed PR changes only this directory; the inherited N256 `opened` one-shot workflow filters to its own workflow file and `qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/**`, neither of which is changed here.
