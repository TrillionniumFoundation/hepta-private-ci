# Kaggle GPU image identity and bounded diagnostic outcomes

This source-only review preserves the failed GPU boundary and makes the request
image contract explicit. GPU quota, a requested accelerator, and provider
`COMPLETE` did not establish an executable GPU environment in these attempts.
The scientific campaign remains **Inconclusive / HOLD**.

## Scope of the reusable patch

`native-batch-gpu-image.patch` applies to the original Hepta Kaggle
`batch-0.1.6` release. It changes only the CLI and batch adapter and adds twelve
behavior tests:

- Accept an optional immutable image from the official Kaggle GPU image repository.
- Accept only the explicit `original` image policy when an immutable image is supplied.
- Bind these optional fields to the durable request intent and official SDK payload.
- Reject a changed image or policy under an existing idempotency key.
- Require the fixed provider version to report the requested image before identity acceptance.
- Preserve existing intent keys when neither optional field is supplied.
- Preserve the existing no-replay behavior after an ambiguous submission acknowledgement.

The patch does not install an adapter, change an account route, change quotas,
create a session, or submit a new cloud request. Apply it to a separate review copy
whose source hashes match `PUBLIC_TESTS.json`; do not apply it over an active
release or mutate an existing request ledger.

```sh
git apply --check /path/to/native-batch-gpu-image.patch
git apply /path/to/native-batch-gpu-image.patch
python -m unittest discover -s tests -v
```

The Python environment must provide the release's pinned SDK dependencies.
Validation used `kagglesdk 0.1.38`: all 65 original tests and 12 additional tests
passed. The patch applied without fuzz to an isolated copy. The original installed
release was unchanged. The test receipt and test log are included in this review.

## Official contract checked

The fixed official Kaggle CLI source at commit
[`fdc788faffe3f29ae317480325c44080a00a5434`](https://github.com/Kaggle/kaggle-cli/blob/fdc788faffe3f29ae317480325c44080a00a5434/src/kaggle/api/kaggle_api_extended.py)
uses `ApiSaveKernelRequest`, forwards `machine_shape`, `docker_image`, and
`docker_image_pinning_type`, and lists `original` and `latest` as valid push
policies. The inspected source SHA-256 is
`78824a5169cff23811f571b795bf54c95d758200daf3336e3b4825a9e5731ea1`.
This bounded adapter exposes only `original`, because the experiment requires an
immutable image contract.

The official [Kaggle Docker image README](https://github.com/Kaggle/docker-python/blob/main/README.md)
distinguishes the CPU image repository `gcr.io/kaggle-images/python` from the GPU
repository `gcr.io/kaggle-gpu-images/python`. The GPU manifest was fetched once
and its body hash matched its registry content digest. No image layers were
downloaded by the controller.

## Three distinct attempts

All attempts retained their original source, request identity, limits, failures,
and provider version. No request was renamed or resubmitted to conceal a failure.

| Attempt | Contract | Provider state | Observed CUDA availability | Acceptance |
| --- | --- | --- | --- | --- |
| 02 | Existing full pilot; 1,800-second provider / 1,740-second worker bounds | COMPLETE | false: qualified device artifact reported a CPU Torch build and no CUDA devices | Failed before model setup |
| 03 | Pinned GPU image; offline; 120-second provider / 100-second worker bounds | COMPLETE | null / unknown: image guard rejected qualified artifact retrieval | Failed: DOCKER_IMAGE_MISMATCH |
| 04 | Same pinned GPU image and `original` policy; same offline limits | COMPLETE | null / unknown: image guard rejected qualified artifact retrieval | Failed: DOCKER_IMAGE_MISMATCH |

For 03 and 04, `actual_cuda_available` and `actual_cuda_execution` are both
`null`. `gpu_execution_verified=false` records the failed acceptance decision;
it does not claim that unobserved CUDA execution returned false. Neither provider
completion nor metadata `enableGpu=true` substitutes for an admitted device
artifact and numerical CUDA probe.

The original adapter already serialized `machineShape=NvidiaTeslaT4`.
Fixed-version provider metadata preserved that shape and `enableGpu=true`, but
reported a CPU-repository image. The two explicit image diagnostics still
reported that CPU-repository image instead of the requested GPU digest:

| Role | Immutable image |
| --- | --- |
| Requested by 03 and 04 | `gcr.io/kaggle-gpu-images/python@sha256:de153e6d303881930c51286216393d56f56b26458d0661350305a1e8144eea01` |
| Reported in fixed-version provider metadata | `gcr.io/kaggle-images/python@sha256:0717e81990be591f8c5f98f033d29ab23e9ffde057e5b3a6bd4371f93969e962` |

The mismatch guard stayed enabled. A separate read-only diagnostic observed
provider terminal status and the metadata mismatch; it did not admit rejected
artifacts or convert metadata into a device measurement. The reason that the
requested image was not reflected remains unresolved. No further parameter
combination was submitted.

Native session capabilities were also read without creating a session. The
available session adapter exposed no creation hard timeout or authoritative
runtime-stop terminal observation. That path could not preserve the existing
bounded execution and cleanup contract, so it was not used.

## Resource and scientific boundary

The planned pilot retained 18 collection episodes, 12 physical training fits,
and 216 development evaluations. All three new attempts completed **zero**
collection episodes, **zero** model fits, and **zero** development evaluations.
The later common-model-warmup and explicit-synchronization source at
`09c2aaf51d033fdc253e3b87f4b590404561681d` was prepared but was not executed.

New material-source HTTP body bytes for this GPU chain were zero. At the handoff
to the next material acquisition stage, the shared ledger remained
17,669,796 / 26,214,400 bytes. This is a handoff value, not a claim about later
material work. The single 20,399-byte registry-manifest response belongs to
compute setup metadata and is recorded separately.

Observed GPU quota used and reserved were both zero at the terminal check.
That does not establish zero total research cost: controller work, failed
attempts, metadata retrieval, and unknown provider CPU runtime remain in the
private research ledger. Missing admitted artifacts leave cloud runtime costs
unknown where they were not measurable; no zero-cost value is imputed.

These infrastructure failures do not generate an adoptable model or a
`NoUpdate` learning result. The finite learning contract still needs qualified
data and evaluation. No zero-delta V5 update was submitted. The complete five
task families, retention, locked independent evaluation, full action-space
controllers with matched opportunities, variance-based independent training
repetitions, frozen/joint A/B/C/D contrasts, and production native-owner
evidence remain separate acceptance gates.

## Exact executed bytes versus this review

The public combined patch is a reusable derivation. It excludes the private task
launcher and its account-route preservation test, and formats the remaining
tests through Python's AST. It is **not the exact task artifact executed for
attempts 03 or 04**.

| Artifact | SHA-256 | Test result |
| --- | --- | --- |
| Actual private task V1 patch | `836214c0c18a1768751d50f669d9c4aa73244fa5232a5c9043e9c53dd6a0ceac` | 73 passed: 65 original + 8 task tests |
| Actual private task V2 incremental patch | `b09ca79ccd0b87b168bfcd95e3904a57565e8509aed7ff18ca3dfa2b6d100438` | 78 passed: prior 73 + 5 policy tests |
| This public combined patch | `81cbabe626120a81857f9fabd803b5643a0748d33e5b14bf1553801a12172578` | 77 passed: 65 original + 12 public behavior tests |

The two patched adapter module bytes match their task V2 counterparts; the
combined patch, tests, and launcher set differ. `PUBLIC_TESTS.json` provides
the per-file hashes and the independent validation receipt for this public
derivation. Raw provider replies, account routing, request identifiers, runtime
custody data, private task launchers, and original execution artifacts remain
in the private evidence archive.
