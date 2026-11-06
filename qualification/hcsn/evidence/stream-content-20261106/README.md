# Stream/content engineering acceptance — 2026-11-06

This evidence qualifies the additive physical-time and typed content interfaces.
It does not establish learned MQAR quality, matched-capacity superiority,
real-media improvement, or a quality/cost frontier.

## Source identity

| Scope | Commit | Full Git tree |
| --- | --- | --- |
| Existing CUDA campaign | `f355cfe2ae96b2bc9a5409f8eeb857894f1b0c5b` | Frozen separately |
| Local execution of new source | `89c6d21e03038d896d57b22149ea4deb23813228` | `172f18c50e4b643127c42dd772ec4f06c49b37d5` |
| Published new source | `5b2b73a5f42ef91733e67bf2d79769dc9d2fe8d1` | `172f18c50e4b643127c42dd772ec4f06c49b37d5` |

The connected GitHub API recreated commit metadata after native Git lacked an
HTTP write credential. The published commits were fetched and their complete
Git trees compared with the executed local commits. Original receipts still
record the actual local execution identity; they have not been relabeled.
[SOURCE_ACCEPTANCE.json](SOURCE_ACCEPTANCE.json) includes the 35 source/config
file hashes checked against the final CPU receipt.

The changes are reviewed in stacked draft PRs
[#4941](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4941)
(time and gradient interfaces) and
[#4942](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4942)
(content mechanism, tasks and loss).
The frozen definition is [CONTENT_MECHANISM.md](../../CONTENT_MECHANISM.md).

## What passed

| Evidence | Result | Interpretation |
| --- | --- | --- |
| Parent CPU suite | 109/109, zero failures/errors/skips | Existing source compatibility; the receipt's source_commit is null, so a separate 29-file source comparison is retained |
| Final CPU suite | 133/133, zero failures/errors/skips | Parent 109 plus 8 time, 9 content-data and 7 content-model checks |
| Final content integration | 108 passed, zero failed, 6 unavailable | 18 CPU-available cores × 6 conditions; official Mamba2 is unavailable in this CPU environment |
| Additional integration controls | 8/8 | Input rejection, query loss authority, no financial computation in smooth gate, irregular-time HX/smooth continuation |
| Actual query-loss boundary derivative | Absolute error 3.688260634404639e-14 | One untrained FP64 directional finite-difference fixture |
| Endpoint refinement | Readout RMS changes 0.0371551105, 0.0023739353, 0.0014933839 | Successive 1→2→4→8 subdivision comparisons on the same held physical input |

The six content conditions are base, query swap, overwrite, silence,
interference and unknown-key queries. Base and silence are identical inputs,
so these are interface checks rather than six independent experimental groups.
Labels come from an independent prefix dictionary checker. That checker and
query payloads do not enter the model. The shared encoder is identity and
routing uses supplied symbolic keys; this is not learned semantic addressing.

The implementation rejects zero-duration typed content intervals. The generic
time integrator preserves state across zero elapsed time, but no instantaneous
content write has been defined. Stream continuation here is same-process
continuation, not a durable process-recovery qualification.

## Capacity and budget limits

Equal width is not equal capacity. For the tiny H=4 integration fixture:

| Core | Trainable scalar parameters | Observed nonzero gradients in the base fixture |
| --- | ---: | ---: |
| HX dual | 208 | 176 |
| HX call / HX risk / margin only | 200 | 168 |
| Smooth gate | 184 | 152 |
| GRU | 176 | 152 |
| CfC | 3620 | 3364 |
| Attention | 396 | 388 |

One batch's nonzero-gradient count is not a structural activity certificate.
No matched active-parameter or equal-search comparison has been run.

The three retained content integration snapshots use zero optimizer updates
and zero CUDA training attempts. Their recorded intervals sum to
37.816195056 CPU seconds and 36.059838724 wall seconds. These totals exclude
interpreter startup, imports, review, other tests and installation. The final
snapshot alone records 8.378491299 CPU seconds and 8.395169389 wall seconds.
The full unit suite includes pre-existing small training/recovery test fixtures;
the zero-update statement applies only to the integration snapshots and
separate untrained time probe. Physical energy is unavailable, not zero.

The original CUDA source, 170 run identities, 400-update budgets, original
`full.json` hash and all previous failures remain separate and unchanged.
Completion of that campaign cannot qualify this newer content source.

## Contents and reproduction

- `parent-cpu-tests.json` and `parent-source-review.json`: untouched parent receipt and file identity review.
- `final-cpu-tests.json` and `final-cpu-tests.log`: final 133-check receipt and log.
- `content-fixture-development-v1.json` and `content-fixture-development-v2.json`: retained earlier engineering snapshots.
- `content-fixtures-final.json`: final integration results and known fixture costs.
- `content-time-probes-final.json`: mechanism/task-loss gradients and endpoint refinement.
- `verify_content_fixture.py` and `verify_stream_fixture.py`: the actual runners; run from the pinned repository root with that root on `PYTHONPATH`, and supply output destinations explicitly.
- `multimodal-readiness.json`: read-only audit of existing real-media assets and unresolved interfaces.
- `SOURCE_ACCEPTANCE.json`: source acceptance and explicit false scientific-qualification flags.
- `MANIFEST.json`: SHA256 and bytes of every payload file, excluding itself.

Runtime versions are recorded in each receipt. The final source was exercised
with Python 3.12.14, Torch 2.8.0+cpu, NumPy 2.3.5, SciPy 1.17.0 and ncps 1.0.1.
Use the pinned published source rather than an evolving branch when reproducing.
Do not treat a result from unavailable Mamba2 or a missing real-media bridge
as a pass.

## Remaining decisive experiments

1. Certify and match active capacity, register the same search trials, seed
   identities, train/evaluation split and stopping rules for every comparison.
2. Train the typed content task and report paired query swap, overwrite,
   silence/interference, unknown keys and held-out generators. Report task
   accuracy as well as state and gradient checks.
3. Freeze one real-media encoder and addressing contract shared by all cores.
   Define simultaneous event ingestion without inventing physical time.
4. Audit gradient and refinement error after training, retaining the distinction
   between stationary conditioned HX features and moving-boundary first passage.
5. Measure complete training/evaluation and failure costs, throughput, latency
   tails, memory, durable recovery and physical energy where supported. Include
   encoder, routing and per-key state costs in end-to-end comparisons.

These are open acceptance gates, not completed results or a new training-budget
registration.
