# Read-only cross-version citation audit for completed Qwen strong RAG

This optional diagnostic is for the **real generating source** `02c12b4aff0d589d10e5ed25d22b05d794ca96a0`, whose GitHub Actions experiment began running on 2026-10-11. The branch later gained formal citation-chain scoring. Do **not** call the later scores native results of the older generator. The tool records the generating and auditing commit SHAs separately.

After the generating run completes and uploads its **72-answer** `memory-strong-rag-calibrated-reader` artifact, independently download that artifact ZIP, retain its externally measured SHA-256, and use the original **externally pinned input ZIP** `11669174727` (SHA-256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`). Do not run this over a partially generated or unpinned archive.

```sh
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/event_posthoc_citation_receipt.py \
  event-inputs-20261010.zip GENERATED_QWEN_RUN_ARTIFACT.zip \
  --generating-commit 02c12b4aff0d589d10e5ed25d22b05d794ca96a0 \
  --result-zip-sha256 EXACT_DOWNLOADED_ARTIFACT_ZIP_SHA256 \
  --auditor-commit EXACT_CURRENT_AUDITOR_SOURCE_COMMIT \
  --output posthoc-citation-review.json
```

The verifier first checks both ZIP outer hashes, safe extraction and complete inner SHA256 manifests. It rejects altered source and reader identity, missing/duplicated task arms, raw-to-scored answer modification, changed source excerpts, citation queues, unmatched program outputs, and mismatched source-selected controls. It re-executes bounded procedure verification and reconstructs exact nine-arm formal citation-chain completeness without invoking a language model. The original model task scores are required to match the generation's own report, preventing citation metrics from changing answer accuracy.

This is **not** a new trained head, new 40+72 reader run, independent human entailment judgment, fresh independent source family or production certificate. The historical eight test scopes are authored and previously exposed. Both generating and auditor SHAs must remain recorded; a successful post-hoc replay is still only an integrity/citation-path check and cannot qualify parametric memory or deployment. In particular, the existing PR-wide formatter/`blocking-ci` acceptance gates remain unaffected by this optional read-only tool.

Seven bounded synthetic-archive and lineage tests exercise the offline verifier without model inference. They do not replace execution of the completed generating run or its original independent replay.
