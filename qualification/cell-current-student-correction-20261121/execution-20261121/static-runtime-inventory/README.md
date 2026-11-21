# E2 runtime inventory — terminal read-only result

**Result: BLOCKED. No exact runtime candidate was found within the declared roots and bounds.** This is one new static inventory, not a continuation or retry of the original 3,600 second recovery.

The single durable ROG job `1a1fc72d23e-ffbe-1da9` succeeded with exit code 0 and complete, durable output. It started at `2026-11-21T04:52:26.542731Z`, had a hard deadline of `04:55:26.542731Z`, and returned all three host results in `0.9325699806213379` seconds. Both existing SSH aliases used `BatchMode=yes` and `StrictHostKeyChecking=yes`; no network or credential configuration changed.

| Host | Observed core materials | Qualification |
| --- | --- | --- |
| desktop | Retained recovery venv config records Python 3.12.3. No five-core-package dist-info was found. The named Torch wheel is the retained 167,587,840 byte incomplete ZIP. | No exact runtime candidate. |
| ROG | `.venvs/rocm10` records Python 3.14.4 and Torch 2.13.0+rocm10.0.0. Retained dependency venv records Python 3.12.3 but has no matching core package set. | Existing ROCm runtime does not match either version or frozen checkpoint.py bytes. |
| ai395 | `.venvs/rocm10` records Python 3.14.4 and Torch 2.13.0+rocm10.0.0. The known `/home/qq/hepta-learn-ff41-tools/python` directory exists; no matching five-package set was found in the declared roots. | No compatible reuse candidate was established. |

Required identity remains Python 3.12, Torch 2.9.1+cu128, Transformers 4.57.3, Tokenizers 0.22.2, Safetensors 0.7.0 and PEFT 0.18.0. The two observed ROCm distributions have metadata SHA256 `e13ff5ee93dee358d80758cb085be36bc2fffd313829a3975566c4a226d4c938`. Their checkpoint.py SHA256 is `eab49639231cc989d65c04212923eef0ade4aa059b68bcabfe2819007f34e69f`, which differs from the frozen required `431b229da53972d79bed7e5dbfb6ace2922fff30192ea103208f484e59490f23`.

The inventory visited 1,125 / 2,866 / 746 directories and saw 12,564 / 28,862 / 7,777 entries on desktop / ROG / ai395 respectively. All host scanners exited 0 with no reported errors or triggered caps. The declared maximum depth was 7; the roots and skip rules are preserved. This is not an exhaustive whole-host absence claim. Six bounded pip `.body` candidates on ROG yielded no matching core wheel. The scan did not inventory all retained NVIDIA dependencies again and does not supersede the original recovery wheel evidence.

## Scope and limitations

The scanner used Python standard-library code with `-I -S -B`, read dist-info metadata and RECORD entries, and hashed the three selected runtime source files when present. RECORD checks established file existence only; they did not verify every entry's content or complete transitive dependency closure. Missing cached bytecode rows on the unrelated ROCm installations are preserved without a claim that those environments are broken. Static pyvenv metadata does not establish executable or CUDA readiness.

Framework imports, CUDA calls, installs, downloads, runtime-material copies, formal CPU encoding, model calls, native evaluation and optimizer updates were all **0**. No scientific budget was consumed and no execution follow-up was launched. The original `dc3397c9e09e29861a0a4fe2267e8ef19e55db01` training source and candidate `dc96ad0c29223dc0fbf0e6165854d8e7cf25331c3f77d57ad30c4f30fc6cf678` remain unchanged.

The original recovery's `03:24:26.254009Z` start, `04:24:26.254009Z` deadline, failure/partial materials, 15.602991 second final cleanup overrun and zero scientific updates remain separate, immutable evidence. This inventory provides no basis to relax module identity gates, change package versions, or proceed automatically to copying, installation, encoding or training.

## Evidence

`STDOUT.jsonl` is the exact 16,418 byte durable stdout; `STDERR.txt` is empty. `INVENTORY.json` parses the five output rows without re-execution. `RESULT.json` records the bounded conclusion and zero counters. `JOB_TERMINAL.json`, `JOB_START.json` and `LAUNCH_ENVELOPE.json` preserve the durable job identity and terminal status. `INVENTORY_OPERATOR.py` is the exact launched scanner, SHA256 `0e0785ba694c3c1d4e6d644cec35dbfd348ebfdca1ee8169a9362213af642358`. `FILES_MANIFEST.json` binds the retained local evidence bytes.
