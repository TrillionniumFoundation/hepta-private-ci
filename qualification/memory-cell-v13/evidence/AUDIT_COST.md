# Independent audit of V13 measured cost and efficacy

## Conclusion

**No tested parameterized-memory task establishes a victory over all strong ordinary controls within the measured cost scope.** The execution does establish actual pretrained encoding, learned residual/head updates, and complete training-state restoration. Those implementation results do not establish a general memory or full-system cost advantage.

This audit reads the fixed experiment outputs and the single authorized latency run. It changes no source, threshold, model, partition, or example selection.

## Warm request measurements

The primary workload contains 72 authored held-out requests, each timed three times. All 1,296 method-request trials are retained. Four encoder methods each perform 216 fresh encoder calls (864 total). The lexical and exact-request controls do not call the encoder. Request and method order are randomly permuted with a fixed seed. The selected operation executes on the real payload; exceptions and abstentions count as failures. Golden-output scoring is outside request latency.

| Method | Executed correct / 72 | Accepted / 72 | Wall p50 ms | Wall p95 ms | CPU p50 ms | CPU p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | 42 | 72 | 0.5082 | 0.8131 | 0.5081 | 0.8132 |
| centroid | 60 | 72 | 6.2753 | 8.0193 | 6.2752 | 8.0191 |
| exact_store | 0 | 0 | 0.0175 | 0.0303 | 0.0175 | 0.0295 |
| nearest | 58 | 72 | 6.2589 | 8.0031 | 6.2588 | 7.9873 |
| ridge | 61 | 72 | 6.2409 | 7.9176 | 6.2409 | 7.9175 |
| single_adapter | 59 | 72 | 6.2984 | 7.7742 | 6.2983 | 7.6805 |

The profiled adapter is the predeclared seed-713 single model: 59/72 correct, versus ridge 61/72 and centroid 60/72. The adapter median is slightly above ridge; its p95 is slightly below ridge. These small timing differences, measured on one resident CPU process, do not establish a statistically reliable speed advantage. Most request time is the shared encoder. Exact-request lookup abstains on every paraphrased holdout request; its small latency cannot be called a semantic-memory win. BM25 is faster but answers fewer requests correctly.

Across the three fixed optimization seeds, single-adapter skill outcomes are 59/72, 61/72, and 61/72; ridge is 61/72 for all three. The profiled timing should not be presented as separately measured timing for the other two seeds. Three seeds reuse the same authored requests and are not independent task datasets.

## Setup, training, and representation bytes

The shared encoder load and pinned-file validation took 0.443291 s wall. Re-encoding all 120 training requests took 0.583177 s wall and reproduced the frozen matrix exactly (maximum absolute delta 0). The already trained adapter checkpoint loaded in 0.008102 s. These are separate from warm request latency.

The archived initial adapter fit took 0.063814 s for 240 Adam updates / 4,800 presentations. The independently rebuilt ridge fit took 0.000984 s, with weights exactly equal to the fixed experiment artifact. This compares incremental fit steps on common features; it is not a complete source-ingestion or lifetime training cost.

| Representation | Bytes | Accounting meaning |
| --- | ---: | --- |
| Shared pretrained ONNX weights | 90,405,214 | One common encoder, not a separate copy charged to every cell |
| Encoder assets and manifest | 470,038 | Tokenizer/configuration/identity files |
| Dedicated installed runtime | 157,091,260 | Directory footprint, including dependencies; not a minimal-runtime or RSS claim |
| Adapter + classification head | 86,112 | Uncompressed float64 parameter arrays |
| Adapter Adam m/v | 172,224 | Continuable training state |
| Adapter sampler order | 960 | Separate from the 691-byte causal JSON profile |
| Adapter checkpoint on disk | 250,047 | Compressed file containing weights, optimizer and causal metadata; not additive to logical arrays |
| Nearest-example numeric index | 369,600 | Features and labels, plus 91 metadata bytes |
| Ridge numeric weights | 36,960 | Plus 48 metadata bytes |
| Authored training rows on disk | 59,692 | Includes evaluator goldens and metadata; not a minimal operational source representation |

The adapter uses fewer numeric bytes than the full nearest-example index, but more than ridge, while achieving lower accuracy for the profiled seed. Even its parameter arrays are larger than the complete training-row file in this small fixture. Consequently this execution does not demonstrate compression of the original evidence corpus. The base encoder remains necessary to use either learned feature model. All failed candidate checkpoints are preserved and separately charged as experiment archives rather than pretending they are free or equating them with minimal deployed storage.

## Project bindings, correction, and composition

Parameter updates genuinely change responses to constructed new project bindings: updated models outperform their frozen versions on the project requests. However, the ordinary nearest/centroid/ridge and explicit project lookup controls also reach 12/12 on every revision frontier. Replay frequently preserves fewer original skills than the frozen parent; the final replay retention is 52/72, 55/72, and 48/72 across the three seeds. Without original-skill replay it falls to 9/72, 9/72, and 11/72. Thus successful new-binding acquisition does not establish a superior continual-memory tradeoff.

A separate one-pass exact-project measurement executes all 12 chronological snapshots correctly with zero encoder calls: wall p50 0.015378 ms, p95 0.087283 ms. It receives the original public project-name request and resolves only journal observations available at its as-of frontier. These are three projects over four linked frontiers, not twelve independent new project tasks. This latency is not mislabeled as the 72-query instruction workload.

On publicly decomposed compositions, nearest-example retrieval reaches 12/12; the single adapter reaches 11/12, 11/12, and 12/12. On source-supplied hybrid policy requests, BM25 reaches 12/12 while the single adapter reaches 10/12. None establishes an adapter result better than every strong control. Executable skills are supplied standard-library programs; the learned behavior is operation selection or project-to-operation binding, not generation of new program semantics.

## Limits on economic and distributed conclusions

These observations do not isolate per-method peak RAM, activation storage, allocator overhead, page-cache residency, energy, queueing, request transport, recovery, or remote-node discovery. The measured local pipeline does not support a claim of distributed throughput or hardware energy gain. Candidate training receipts and checkpoint archives are recorded, but an amortized economic winner would additionally require a declared request/update mix and comparable quality/coverage. No such full-cost win is claimed here.

## Evidence

- [Complete latency and storage record](run/LATENCY_COST.json).
- [All experiment outcomes](run/RESULTS.json).
- [Raw profiler stdout/stderr](checks/latency-cost.log).
- [Profiler exit status, command, and thread controls](checks/latency-cost-meta.json).
- [All 24 scoped correctness tests](checks/scoped-tests.log).

LATENCY_COST.json SHA-256: `e7cad4429e948a37f413043090d4beb0b7dc53379b118ea274fd92291ada5285`.
Profiled checkpoint SHA-256: `5f28dbda0393259005091a2fde9f56dd99837f4667e4924affd9906e8b0f7719`.
Encoder identity hash: `8b8d070f392fd30181f217daa4de166dfe785897b5d4d64f2244bc6fcb5f42aa`.
