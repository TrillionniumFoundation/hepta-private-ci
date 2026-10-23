# Opt-in derived Laya read-only SDK comparator

**DRAFT / RESEARCH_ONLY / HOLD_NO_GO.** This comparator is never imported or enabled by `run_models.py` or `retrieval.py`. Their unchanged strict artifact and calibration guards remain the default. A derived SDK profile is not the frozen original runtime, and this directory does not narrow the original five-model or 11+ option requirements.

## Why a separate comparator

Official Laya 0.4.14 rewrites the pinned Multilingual tokenizer configuration during loading. Existing [P41 #3445](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3445), exact head `4b672808ceaa13597d7792201e06a82e0819b750`, instead isolates and discloses this upstream rewrite in temporary tokenizer assets. That is a related, distinct compatibility profile, not duplicated here.

This candidate makes an explicitly derived source copy of the official SDK. It replaces the tokenizer file repair with standard transformers in-memory keyword arguments. It changes only `agent.py` and the new `readonly_tokenizer.py`, never the installed shared SDK. Architecture, weight loading, question encoding, calibration/clamping and decoding source are unchanged. The frozen artifact guard still checks every file after candidate loading/inference and before exit. The original reference uses a disposable copy and must exhibit exactly the known tokenizer rewrite; it is diagnostic, not an unchanged-artifact acceptance receipt.

The derived profile is `laya-0.4.14-local-readonly-extra-special-token-map-v1`. It is restricted to this pinned tokenizer class/configuration. Unsupported classes and malformed special-token schemas fail closed. It removes upstream's parsed-tokenizer cache, so startup/performance equivalence is not claimed. Local-only/no-custom-code assurance applies to the fixed validated snapshot and probe, not arbitrary calls to the derived Agent class.

## Exact public sources and license

- [Official Laya 0.4.14 wheel](https://files.pythonhosted.org/packages/89/6a/e8fd7c88ba87cec0896bf1edb9742f512c7dc79d7107270e88e624785f45/laya-0.4.14-py3-none-any.whl), SHA256 `e547dd6670528114458355f66666b1e5f23e481361ba658a7e8a635e8b080e8a`.
- [Pinned Multilingual publisher snapshot](https://huggingface.co/convaiinnovations/laya-multilingual/tree/1720e3e3357cfe1e281542e223f8273b0890ca34), weight SHA256 `9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204`.
- `upstream.json` binds the official Python source tree, wheel and license; `sdk-source.patch` is the exact derived source delta. `LICENSE` preserves the upstream Apache-2.0 license. This is not an upstream-endorsed release.
- `snapshot.json` binds all seven retained original files. These observed public hashes are not independent artifact-owner signatures. Model files are not vendored here.
- `cases.json` uses three examples from the pinned public model card, plus explicitly mechanical repetition/Unicode/control perturbations. It contains no private user task data and no accuracy labels.

## Reproduce explicitly, outside normal CI

This location-portable diagnostic profile is explicitly Linux-only (CPU affinity and Linux resource accounting). Use an isolated environment, Python 3.12, torch 2.8.0+cpu from the official CPU package index, transformers 4.57.1, Laya 0.4.14, NumPy 2.2.6, safetensors 0.8.0, tokenizers 0.22.2 and huggingface_hub 0.36.2. Optimized Python (`-O`) is refused so evidence checks cannot be disabled. Verify the official wheel digest above; the builder also verifies all installed Laya Python files and its license before copying. No download, dependency installation or model execution happens in normal contract CI.

Materialize only the seven files listed in `snapshot.json` from the pinned public revision into a directory whose basename is that revision. Do not use the SDK-mutated cache as the original. Let `SNAPSHOT` be that directory, `WORKSPACE` be a new output directory, and `PYTHON` be the isolated environment's interpreter. From repository root:

```sh
$PYTHON qualification/neuron-model-bakeoff/sdk_readonly/build_candidate.py --output "$WORKSPACE"
$PYTHON qualification/neuron-model-bakeoff/sdk_readonly/run_probe.py official_reference --workspace "$WORKSPACE" --snapshot "$SNAPSHOT"
# Wait for the first process to exit. Never hold both original models resident.
$PYTHON qualification/neuron-model-bakeoff/sdk_readonly/run_probe.py readonly_candidate --workspace "$WORKSPACE" --snapshot "$SNAPSHOT"
$PYTHON qualification/neuron-model-bakeoff/sdk_readonly/compare.py --workspace "$WORKSPACE"
```

The builder and each probe reject existing output locations instead of overwriting evidence. The driver fixes CPU fp32 eager, two threads/affinity slots, offline mode, exact package versions and the full original inventory. It rejects missing encoder/tokenizer files or a custom-code encoder config. Sequential original/candidate processes use identical inputs and model settings. Full source manifests, case/driver hashes, repository head/dirty status and guard hashes are recorded; dirty source is disclosed, not presented as independent attestation.

The comparison requires seven groups / 17 actual rows, all five actual model inputs and both raw logit outputs, exact byte equality with dtype/shape/hash checks, matching decoded answers and real truncation accounting. It binds current driver, fixtures and derived source manifest. Raw `.npy` tensors are external run artifacts, never repository source. Only the enumerated fixture is compared, not all possible inputs.

## Tests and retained observations

```sh
python3 -m unittest discover -v -s qualification/neuron-model-bakeoff -p 'test_*.py'
$PYTHON qualification/neuron-model-bakeoff/sdk_readonly/check_tensor_comparator.py
```

The standard-library suite discovers `test_sdk_readonly.py` through the existing focused workflow; no ML package is needed there. Tensor-comparator tests are a separate explicit command in the isolated model environment.

`observed-20261023/` retains the earlier reviewed local diagnostic: seven forwards / 17 rows per profile, 49 bit-identical actual input/output tensors, matching decoded answers, unchanged original artifacts and candidate copy, preserved official-reference rewrite. The exact historical driver/comparator texts and source manifest are retained; their reports must not be relabelled as executions of subsequently portable CLI source. The separately delivered full diagnostic archive contains the raw tensor evidence, SHA256 `134ad91da4913a9c39ed319e39b75752a546324e2597f3cd7df42ec1ba95f374`.

`observed-portable-20261023/` records the fresh portable-driver repeat: another seven forwards / 17 rows per profile and 49 bit-identical tensor comparisons, unchanged original/candidate artifacts, unchanged calibration, and the same retained official-reference rewrite. Probe SHA256 `8fe4ce3ea3c7b776d42a7f4408707a8aa085a93a3b8ee60e05cffefe992d87db`; comparator `476b9c60cfb6946bcb0ba3e0ba2126d651668cf3c882d954770135985789efa5`; result `150d25bd30a008fd22caa4397bd08c0ac9549c52c7cb5e412bb374c0e3cbb866`. `pre-receipt-source.json` identifies generating pre-receipt source tree `c24e4428da09f83417d8c3594b6059fc6ec5aa7a` atop #3568, with uncommitted source disclosed. Later publication adds these receipts, documentation and a test-only platform skip. It is not a claim that a commit generated its own receipt, nor independently witnessed execution. No model source, fixture or comparator changed after that repeat. Hosted CI is source-only contract validation, not model execution or parity evidence.

## Open gates

The unmodified official SDK still mutates Multilingual configuration. English/Typed's `choice:11+` raw/effective calibration mismatch remains blocked under the strict default; no clamp is removed, failed bucket discarded, calibration refitted to force pass or hidden 2–10-option restriction introduced. The publisher says Multilingual's unit temperatures are uncalibrated: preserving them proves identity, not calibrated confidence.

No replacement-quality, independent task data, OOD/calibration, equal-budget five-model experiment, future benefit, scaled Cell resources, signed CAS/lifecycle, production activation or Final-use authority is established. No merge or promotion is requested.
