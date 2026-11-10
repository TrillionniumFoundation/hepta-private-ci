# PERC semantic and owned-entry qualification — checkpoint

**Scientific result: HOLD / NoUpdate.** The final controlled semantic experiment executed real frozen MobileNet inference, but neither neural policy improved terminal quality or resource use over the strong rule policy.

**Publication status:** this checkpoint preserves both complete benchmark reports, the final process envelope, a handoff record, and exact verified source snapshots for five final Python modules plus the compiled Rust probe driver. The complete tested implementation and full raw evidence still reside in the isolated local checkout. Full source publication and the last native-consumer acknowledgement are pending recovery of the execution connector. This is a draft checkpoint, not an adoption or merge recommendation. The runtime source tree is unchanged; CI on this evidence/snapshot commit does not validate the unpublished implementation.

Baseline: `72569fba94a38f7bb0628409cbb05b62fa6c9627`, the head of the existing PERC canonical-test-roots stage (#5683). No production Rust source, native authority grant, daemon integration, or default policy was changed.

## Final experiment

`REPORT_BENCHMARK_V2.json` is the exact locally read-back report, including its trailing newline:

```text
SHA-256 b6be7681e6813bf61a9e83904ee49bbcc055caf69f70f2697357dca818a18daa
```

The generator seed was `2026111001`. Five controlled families cover semantic localization, occlusion, layout variation, temporal change, and text/image complementarity. They contain 60 TRAIN, 20 reserved but unused DEV, and **30 distinct synthetic confirmation tasks**. The three training seeds are `1101 / 2202 / 3303`; they repeat those same 30 tasks.

| Policy | Correct / executions | Completed online encoder calls | Continuation reads | Cumulative online wall time |
| --- | ---: | ---: | ---: | ---: |
| Rules | 90 / 90 | 0 | 90 | 0.196993453 s |
| Global | 49 / 90 | 108 | 149 | 6.704176951 s |
| Dense | 63 / 90 | 108 | 138 | 6.735790162 s |
| Direct-ROI oracle | 90 / 90 | 0 | 90 | 0.044437444 s |

The oracle receives private answer locations and is excluded from fair policy comparisons. Keep direct ROI as a strong baseline when the actual task supplies valid coordinates.

The two neural policies required approximately 34 times the rule policy's online time and returned fewer correct terminal answers. The final run completed 6 fits, 1,200 optimizer updates, and **432 successful encoder batches**: 72 during TRAIN-only PCA collection, 144 during head-training collection, and 216 during online evaluation. These counters count successful finite feature batches, not every attempted forward or failed device operation.

The complete process envelope was 31.53 s wall, 31.01 s user CPU, 0.52 s system CPU, and 339,752 KiB peak RSS, exit 0. This inclusive envelope must not be added to its internal phases. Energy and paid provider costs were not measured.

### Fairness and evidence scope

The fair policies receive the same public target semantics, images, neutral full-grid candidates, and acquisition limits. Public tasks contain no evaluator answer coordinates. Six heads are frozen before confirmation scoring. A changed private answer cannot alter an actor's decision.

Source codes and numeric answers are preserved as original UTF-8 text with exact byte spans and source hashes. The generated numeric codes are not painted into the images. This is source-text fidelity evidence, not OCR accuracy evidence.

Disjoint document/template/source group IDs and augmentation inheritance are checked, but all examples share a controlled renderer and grammar. These are not independent unseen organizations or real-world source collections. Ninety executions are not ninety independent tasks.

| Policy | Logical input observations | Extra immutable PNG reads by encoder | Input file reads |
| --- | ---: | ---: | ---: |
| Rules | 198 | 0 | 198 |
| Global | 257 | 108 | 365 |
| Dense | 246 | 108 | 354 |

The extra image reads are included in wall/CPU time. These file counts exclude weights, source verification, and bookkeeping I/O.

## Native-wire persistence repair

The first complete run, `full-v1`, produced the same scientific results. Its canonical JSON archive reordered nested observation keys, whereas the existing native wire digest depends on the original serde-compatible field order.

The repair retains the original native bytes as bounded Base64 before canonical serialization and keeps the producer's own receipt unchanged. The local owner envelope verifies the producer hash, original byte length/hash, strict JSON, and typed semantic equality.

`full-v2` repeats the same cohort and hyperparameters to validate this persistence repair. It is **not additional independent confirmation**. The two runs have identical 360 terminal outcomes/read counts, 270 fair-policy rankings, 360 feature hashes/Q24 vectors, TRAIN backbone bytes, and six fitted heads/optimizer traces.

The final local audit verified 360 retained original native wires, 288 PCA feature rows, 467 exact quoted source spans, and 90 task × seed groups with equal public packets and initial image hashes. Earlier outputs and failed setup attempts are retained locally, not overwritten.

## Ordinary owned CLI evidence

The implementation adds `python -m perc1 capture` and `capture-read` for operator-pinned local file snapshots. A POSIX single-writer owner durably reserves a unit before acquisition/encoding. It binds operation identity, source frontier, generation, backend, grant, and model. A dispatched operation without a retained receipt remains UNKNOWN and is not silently replayed.

The first real owned-CLI qualification passed:

- Fresh capture: one source callback, one real MobileNet batch, four crops with `4 × 576` features.
- Same-operation replay: exact original receipt and native wire, zero new source callbacks or encoder loading.
- New-process cold read after deleting the run-owned image, text, and weight copies: exact original receipt and wire, zero new encoding.
- A next task recovered amount `0042.50` and entity `Hepta Labs` from retained UTF-8 spans.
- A new operation with a missing source retained its failure and budget charge.
- The over-budget operation was rejected without changing journal rows or capture files.
- The shared original weight file stayed unchanged.

The owned report SHA-256 is `e3e13b7640fef0f77e0d5926c4a8e0ace88be60f4ed7ebcae33a2d0f0e12da9b`. The process envelope was 4.858137091 s wall, 4.711349 s waited CPU, and 329,220,096 bytes largest waited-process RSS.

This uses generated engineering inputs and an ordinary pinned-file CLI. It does not establish live desktop/camera acquisition, production daemon integration, distributed-store fencing, or terminal task benefits from latents. The benchmark, owned CLI qualification, and native Cell probe are separate evidence paths.

## Validation and remaining acknowledgement

The final local PERC regression discovered 127 tests: **126 passed, one skipped, zero failures/errors**. The skipped existing real-document integration requires an unavailable `PERC_TEST_DOCUMENT_DATASET`; no substitute dataset was invented. Real producer tests used the official pinned checkpoint. Canonical `just fmt` passed with unchanged Python ASTs; source hashes remained unchanged during the final test run.

A standalone probe successfully built the unchanged real `hepta-types`, `hepta-infer-core`, and `hepta-neuron` libraries. It exercises the actual `PerceptionCellEncoderV1`, not a substitute implementation. The subsequent consumption command for the owned original wire was submitted just as all local execution/read tools began returning `MCP -32603 Internal error`. **Its execution outcome remains unconfirmed.** Do not claim the positive consume or five negative controls passed until their output is read back.

This is an execution-connector failure, not a permission rejection. Ambiguous mutations were not resubmitted.

## Verified partial source preservation

[SOURCE_SNAPSHOT.json](SOURCE_SNAPSHOT.json) binds exact bytes and original paths for five complete final Python files under `retained-source/`: owner, capture adapter, semantic generator, semantic benchmark, and the real CLI qualification driver. It also binds the unchanged compiled Rust probe driver.

These bytes came from complete read buffers and match the final execution identities. Historical pre-format drafts with different hashes were excluded. This snapshot is incomplete: the CLI entry, shared semantic contract, policy, native Python builder, and tests still need readback from the original checkout. It is deliberately outside the runtime source tree and is not runnable as a complete candidate.

The prior `REPORT_BENCHMARK_V1.json` and exact `PROCESS_BENCHMARK_V2.txt` are also retained without rewriting their original contents.

## Resume without repeating compute

The tested checkout is `desktop:/home/qian-qi/worktrees/hepta-perc-semantic-20261110-d338`; retained evidence is `desktop:/home/qian-qi/perc-semantic-evidence-20261110-d338`.

1. Reconcile `review-native-v1/native-readback/RUN.json` and `RESULT.json` before issuing another native invocation.
2. Reconcile the last metadata-only audit operation in `full-v2/ATTEMPT_LEDGER.json`, `INTEGRITY_V2.json`, and `FILE_MANIFEST.json`. It only renames candidate labels and updates their hashes.
3. Preserve all source snapshots, raw logs, synthetic inputs, projections, fitted heads, receipts, and previous attempts in a complete archive. No new model run is needed.
4. Publish the tested source in reviewable stages: contracts, durable owner, ordinary entry, semantic data/policies, online benchmark, and native/CLI verification helpers. Land the contracts stage first if the full change is split.
5. Publish the evidence archive with an exact SHA-256 asset exception if it exceeds the repository's 500 KiB limit. Retain the default size policy for other bytes.
6. Verify remote bytes and inspect CI. Keep scientific adoption HOLD until new independent task evidence shows net terminal benefit or equal quality with fewer resources.

`CHECKPOINT.json` records exact current status, identities, and outstanding paths.
