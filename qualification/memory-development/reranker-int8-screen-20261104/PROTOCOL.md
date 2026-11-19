# Fixed CPU dynamic-INT8 engineering screen

## Result: DOES_NOT_QUALIFY

One preregistered candidate completed all 12 fresh-process sessions but failed the numerical-fidelity policy:

| Measure | Fixed threshold | Observed in all six pairs | Gate |
|---|---:|---:|---|
| Maximum absolute raw-logit change | <= 1.0 | 1.770819 | Fail |
| Mean absolute raw-logit change | <= 0.25 | 0.256246 | Fail |
| Identical complete top sets | >= 11/12 queries | 12/12 | Pass |
| Margin-filtered ranking concordance | >= 0.98, at least 36 pairs | 68/69 = 0.985507 | Pass |
| Repeated-session score drift within each arm | <= 0.000001 | 0 | Pass |

The engineering failure is the final result. Better warm performance does not override either failed logit threshold. These fictional inputs have **no relevance labels**. This is not a task-utility result or a deployment recommendation.

The complete publication-safe aggregate is `aggregate_results.json`. It includes all six paired cost observations, both arms' absolute ranges, per-length summaries, every gate, setup costs, and methodological limitations. It excludes raw session logs, machine identifiers, local paths, credentials/approvals, runtime installations, model bytes, and private run artifacts.

## Costs, including unfavorable ones

Across the six paired sessions:

- Warm throughput was **1.845–1.939 times** FP32; p95 request latency was **0.579–0.653 times** FP32.
- The **first completed query was 3.58–8.23% slower** with INT8, including fresh interpreter, imports, verification, loading, quantization, tokenization and inference.
- **Startup-plus-inference peak RSS was 2.71–5.07% higher** with INT8. FP32 peaks were 520.02–523.50 MiB; INT8 peaks were 536.16–546.37 MiB.
- Readiness after two full warmup cycles was earlier for INT8. The fixed 500-request projection, readiness cost plus 500 measured mean request times, was 0.530–0.553 times FP32. This is a linear projection, not measured deployment traffic. A zero break-even count for this readiness-based projection does not erase the slower first response.
- An in-memory serialized state occupied 90,894,880 bytes for FP32 and 58,630,728 bytes for INT8, a ratio of 0.645039. **This is not verified disk or deployment savings.** Both arms loaded the same 90,870,598-byte FP32 safetensors file and the same 91,815,758-byte source asset bundle. No saved INT8 reload path was tested.
- Serialization-inclusive process peaks are retained separately. A temporary serialization buffer is larger for FP32; its difference must not be presented as inference-memory savings.

The complete command took **246.00 seconds** externally, or 246.01 seconds with the prescribed rounding allowance, below the 600-second ceiling. The monitored combined supervisor/active-worker peak was **632.47 MiB**, below 2 GiB. One primary attempt completed with exit status 0. There were no result-driven fixes or model reruns.

## Publication-copy status

This is a **post-run publication document**, not the literal preregistration document. It reports the preregistered method and executed result together. The executable Python files, fictional fixture, fixture builder, numeric protocol, runtime pins and tests are copied byte-for-byte from the executed sources. No measured algorithm, threshold, fixture or candidate has been edited for this release.

`seal.json` and `release_manifest.json` seal this publication package, not the original execution environment. Their hashes are release-copy hashes. The release manifest identifies unchanged source copies and the newly written documentation/aggregate. No model, dependency directory, admission/approval record or original worker log is distributed.

## Fixed model and implementation

The public model is [cross-encoder/ms-marco-MiniLM-L6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/tree/233902d25c440f23af6f7d6e94d2946bac0bee0a), revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`. The `model.safetensors` SHA-256 is `821d1aa69520101d6e0737f78a042ae25b19e5cb9160701909d10434f4aeb0ae`. The immutable upstream model card/API identifies Apache-2.0. A standalone LICENSE endpoint returned 404, which was recorded rather than silently treated as a downloaded license file.

Runtime pins: Python 3.12; PyTorch 2.5.1+cpu; Transformers 4.57.1; safetensors 0.6.2. Acquisition used only the official PyTorch CPU wheel index, PyPI binary wheels, and immutable Hugging Face asset URLs. Wheel SHA-256 identities, installed distribution-file identities and Python executable/build identity were checked before execution; installed identities were verified again after the run. This does not claim to hash every operating-system library.

Baseline: FP32 CPU, evaluation mode, inference mode, eager attention. Candidate: dynamic quantization of every `torch.nn.Linear` to qint8, fbgemm, default observer, `inplace=False`. All 38 expected Linear modules were replaced in every INT8 session. No FP32 Linear fallback remained. All loading diagnostics had zero missing, unexpected, mismatched or errored keys. The copy induced by `inplace=False` was included in startup cost and peak memory.

Only locally verified safetensors/config/tokenizer data were loaded. `trust_remote_code=False`, `local_files_only=True`, and `use_safetensors=True` were explicit. Remote code mappings, unlisted asset files and symlinks were rejected. The workers rejected network operations. No downloaded model code or pickle input was executed.

Both arms used one CPU affinity, one intra-op thread, one inter-op thread, disabled tokenizer parallelism, the same eager attention path, the same tokenizer and the same four-passage batch. Machine identity is intentionally omitted; the performance result is specific to the one tested host, not a portable speed guarantee.

## Original fictional fixture

`fixtures.json` contains 12 original fictional queries, each with four passages: 48 query/passage slots. Four queries each have 48-, 112-, and 224-word passages. Two queries contain exact duplicate passages for tie handling. There are no relevance annotations or inferred truth labels. `fixture_builder.py` reproduces the exact input file.

Each request scores one query against its four passages with dynamic padding, longest-first truncation, and maximum encoded length 384. Token fingerprints were identical across sessions. No pair was truncated in this run. Word-length strata are not token-length strata. All pairs were used; none were removed or selected after observing scores.

The short, medium, and long groups had mean absolute logit changes of 0.411621, 0.140630 and 0.216488, respectively. Their margin-filtered ranking counts were 23/23, 22/23 and 23/23. These stratum summaries are descriptive; the preregistered ranking gate was overall, not retrospectively redefined per stratum.

## Sessions, timing and resources

There were six paired sessions, 12 fresh exec-spawned workers. FP32→INT8 and INT8→FP32 pairs alternated. Each worker performed a first request, two complete warmup cycles, one canonical scoring pass, and five complete timed cycles. The starting query rotated by timed-cycle index.

Each worker timed 60 requests/240 pairs. The full run timed 720 requests/2,880 pairs; loading, first responses, warmups, canonical scoring, byte measurement and teardown were additional work. Requests and within-process cycles are dependent observations, not independent statistical replicates. The six session pairs are the comparison units. No confidence intervals or population claims are supplied.

Three costs were recorded: launch to first completed query; launch to readiness after warmups; and launch through process exit and usable result reading. Warm timing includes tokenization, padding/truncation, forward inference, finite checks and Python score extraction. Throughput is four times requests divided by summed request duration. P95 is the nearest-rank percentile. Raw worker timings were preserved for audit but are not in this aggregate-only publication.

The timing condition is **process-cold, OS page-cache uncontrolled**, not disk-cold. Integrity hashing reads the model bytes and warms the page cache. No cache flush was claimed.

The frozen primary supervisor enforced 45 seconds per worker, 600 internal seconds, and a monitored 2-GiB combined supervisor/worker RSS condition. The external complete-command clock independently includes supervisor interpreter/import startup. Linux VmHWM was used for per-exec peak RSS; `ru_maxrss` was diagnostic because an ancestor peak can survive exec. RSS sampling used 50-ms intervals and is approximate, not a hard instantaneous cgroup reservation. Startup/inference and serialization-inclusive peaks are distinct.

## Preregistered decision policy

All gates had to pass. Missing, nonfinite, incomplete, integrity-failed or resource-failed output could not pass. Raw single-output logits were compared, not sigmoid probabilities.

- Maximum absolute logit difference <= 1.0; mean absolute difference <= 0.25.
- Tie epsilon 1e-6. A top set contains all passages within epsilon of the maximum. At least 11/12 queries must have overlapping top sets, and at least 11/12 must have identical complete top sets. Candidate tie inflation does not count as exact agreement.
- For passage pairs with FP32 separation >= 0.1, require at least 36 comparable pairs and >= 0.98 same-sign concordance. A candidate tie on a separated reference pair is non-concordant, not dropped.
- Maximum repeat score drift within each arm <= 1e-6. Duplicated inputs must tie within epsilon.
- Serialized-state byte ratio <= 0.75.
- In every paired session, throughput ratio >= 1.10, p95 latency ratio <= 1.05, and fixed 500-query projected total cost ratio <= 1.00.

These are prospective engineering tolerances, not relevance or statistical thresholds. Numeric failure remains failure even when ranking and speed gates pass.

## Setup and operational deviations

Acquisition downloaded 316,636,127 artifact-body bytes and took approximately 263.257 cumulative seconds, including a recorded pause and correction. Pip index/metadata, TLS and HTTP overhead were not metered. Setup elapsed time used a reconstructed original start plus monotonic continuation, not an exact external setup-command clock. Setup acquisition is recorded separately from local primary startup, not silently treated as free.

Two pre-execution issues were documented without altering the frozen model experiment:

1. An acquisition-only wheel parser counted nested vendored metadata as multiple package metadata records. The parser was corrected to select one top-level `.dist-info/METADATA` with a matching top-level RECORD. Already downloaded official wheels were reused. Nested files remained ordinary installed content covered by integrity checks. No model had been invoked.
2. The originally specified `/usr/bin/time -p -o private_outer_timing.txt` executable was absent. That launch returned exit 127 before the supervisor started, so it was not a model attempt. A documented pre-execution substitution used the parent shell's builtin `time -p`, with separate command stdout/stderr and immediate exit-status capture. The same supervisor command and unchanged condition **outer real + 0.01 <= 600 seconds** were used.

The frozen primary sources were not changed. Exactly one primary model attempt followed and completed. No subsequent model call, threshold adjustment or candidate search was performed.

## Source inspection and local synthetic tests

The package is an audited source snapshot, not an included model/runtime installation. The stdlib-only check is `python -m unittest -v test_protocol`. It uses fabricated numeric outputs and original fictional inputs; it does not load a model or establish model integration success. The actual primary's integration checks are reported above.

The supplied execution harness retains explicit admission, approval, integrity and no-rerun guards. A publication-package seal is not an authorization record and does not recreate the original execution. Any independent future use must establish its own assets, runtime identities, permissions, output directory and pre-execution protocol; it must not be presented as another attempt in this completed run.
