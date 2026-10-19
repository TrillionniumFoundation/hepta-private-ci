# MemoryCell: intercepted Qwen calibration is partial, not an experiment result

**Status: fail closed; no selected top-k, no test answers, no independent semantic review, no production admission.** This is a read-only audit of the genuine, interrupted CPU model run [#38111452963](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963). The source commit that generated these bytes was `02c12b4aff0d589d10e5ed25d22b05d794ca96a0`, *not* the latest working branch or any completed nine-arm evaluation.

## Immutable evidence

The GitHub Actions artifact [#11696974258](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963/artifacts/11696974258) was downloaded and checked using both the **outer ZIP SHA-256** `129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8` and the **25 internal SHA256SUMS member pins**, with the complete file census, safe ZIP paths, source-commit file, model inventory digest, calibration-only manifest, original-source excerpts and their citation-request bindings verified. The original JSONL is SHA-256 `c644cd7ef62c06a2489ab9d9a67c0933ad489a2a8626de73000d27e45df9db71`.

The preregistered calibration has **8 source-separated questions × k ∈ {1,2,3,4,6} = 40 real generations**, with the fixed Qwen reader identity `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`. After the hosted job was cancelled, only **4/40 successful original generations** had been durably journaled: one question, `controlled_4b61ce33`, with k1, k2, k3, k4. The remaining **36 are missing, not wrong and not zero-cost**.

| Original arm | Reader input tokens | Generated tokens | Measured reader seconds |
| --- | ---: | ---: | ---: |
| k1 | 504 | 7 | 923.308 |
| k2 | 787 | 6 | 1,457.513 |
| k3 | 1,076 | 14 | 2,045.598 |
| k4 | 1,370 | 13 | 2,641.516 |
| **Recorded total** | **3,737** | **40** | **7,067.934** |

These are **four model calls**, not four task-family comparisons. The old source was unusually slow (over 117 minutes of summed generation time for these four calls); its throughput must not be projected to the newer bounded-thread reader implementation or interpreted as production service throughput. The `reader` job's calibration step was cancelled; the nine-arm test and independent replay never ran.

The interrupted calibration archive includes calibration-only labels, which **the attached auditor deliberately never opens**. It contains **no** completed `scored-answers.json`, `frozen-policy.json`, test answer journal or valid top-k selection. The observed predictions have no approved task correctness score. No claim of memory superiority, citation entailment, prospective generalization or 99% precision can follow from this artifact.

## Reproducible, fail-closed inspection

Run the standard-library-only verifier on the unmodified official artifact ZIP:

```sh
python scripts/memory_cell/interrupted_qwen_receipt.py \
  strong-rag-partial-reader-38111452963.zip \
  new-interrupted-calibration-receipt.json
python -m unittest discover -s scripts/memory_cell \
  -p test_interrupted_qwen_receipt.py -v
```

It refuses changed archive hashes, missing/extra manifest members, duplicate or nonfinite JSON fields, duplicate or moved candidate selections, source-text substitutions, detached native citation metadata, false reader identity and fraudulent policy/evaluation results. It emits an **explicit non-qualification receipt** with `selected_k=null`, `calibration_complete=false`, `evaluation_started=false` and `production_accepted=false`; it does **not** touch model weights or require the ground-truth label file.

## Proper next-stage qualification

A separate sharded Qwen attempt [#38146546731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38146546731), at this inspection, had **successfully completed source preparation** and started several of the **16 calibration shards**; its other jobs were queued. This is independent *execution of the same authored benchmark*, not 16 independent task families. Its success depends on a complete exactly SHA-bound 40-answer calibration, then 72 frozen nine-arm answers, followed by the separate original-answer replay and citation-chain audit. No result or cost from this interrupted run may fill missing rows in the sharded experiment.
