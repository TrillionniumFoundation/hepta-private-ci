# NEU-1 real Cell model bakeoff — execution package (NOT acceptance)

This package implements the first **reference-execution and evidence-scoring** layer for `NEU-1-LOCAL-MODEL-BAKEOFF`. It does not replace `neuron.runtime`, install a selected artifact, issue a Final-use grant, claim a production backend, or self-certify a score. It is subordinate to `docs/DEVELOPMENT.md`, `docs/learning/EXPERIMENTS.json`, `docs/learning/NEURAL_BIOMIMICRY_SPEC.md`, and `qualification/module-execution-dossiers/LEARNING_EXPERIMENT.md`.

## Reality / identity

The review baseline for this package is main `f8c9419df6ddeb36ff8b522a50219981fb8d9345`. **Do not use that SHA to run the new package.** The evaluated source SHA must instead be the exact eventual PR/merge candidate being executed. Copy `plan.template.json` outside the tracked tree and fill its `source_sha` from `git rev-parse HEAD` after selecting a clean candidate. Its `null` fields are intentionally unqualified, NOT defaults for promotion.

Five separate checkpoints are measured: `laya_english`, `laya_typed`, `laya_multilingual`, `arctic`, and `harrier`. One immutable Hub commit and an inspected on-disk SHA-256 inventory (including weights/tokenizer) per checkpoint are mandatory. Do not use `main`, `latest`, symbolic tags or a model-name string as an artifact identity. Pin the model Python packages and device/runtime separately in an external lock/host manifest. The Laya tokenizer config file which Laya may rewrite is omitted from `freeze_candidate.py`'s byte inventory; its exact Hub source commit and handling require separate inspection before accepting a consumer. The Laya `action.act_probability` is NOT an authorization signal.

## Dataset contract

Produce a JSONL file with one immutable **decision question per line**, at least 30 independent calibration groups, and at least one successful test/retention row. Each row has:

```json
{"id":"q-001","group_id":"episode-001","split":"test","task":"triage","language":"en","state":{"body":"Replace with authorized observation"},"instructions":"Which queue?","criteria":{"billing":"payment","technical":"software"},"gold":"billing","ood":false}
```

Allowed splits: `train`, `calibration`, `test`, `ood`, `retention`. For OOD rows, set `ood:true`, `split:"ood"`; gold is not used. Group by correlated **episode, principal, source and temporal block** before splitting. The implementation rejects repeated IDs, correlated group overlap and identical rendered input across splits. This is not a substitute for independent source-group/deduplication audits. Preserve independently observed labels and future-window watermarks separately; do not recycle public Laya typed-decisions test results as Hepta's independent holdout. Keep private source data off GitHub and GitHub Actions.

For retrieval, supply `queries.jsonl` rows like `{"id":"query-1","text":"...","split":"test","relevant_doc_ids":["doc-1"],"group_id":"episode-1","language":"en"}` and `corpus.jsonl` rows `{"id":"doc-1","text":"..."}`. Freeze both SHA-256 before inspecting candidate predictions. Use the same queries and corpus for Arctic and Harrier, and preregister any model-native query prompts.

## Six steps (strict order)

1. **Baseline** — freeze real Laya English 421M and Laya Typed 421M weights, dataset, host, libraries and head/question schemas. Score identical **independent** test rows. Do not mistake Laya Typed's published in-domain 0.766 for an independent Hepta benchmark.
2. **Direct replacement** — run Laya Multilingual 322M on identical rows and multiple representative languages. Compare full-denominator accuracy, class-macro recall, calibrated ECE/Brier, confidence/coverage and per-language floor.
3. **Encoder comparison** — use frozen Arctic 305M and Harrier 270M. Train one **linear head per fixed task ontology** with the same 256-dimensional seeded Gaussian projection, identical training rows, 40 epochs, minibatch size, optimizer/weight decay and seed as frozen in `head_training`. Save a new head digest, separately report actual model FLOPs, latency and bytes, and run equal-qrels retrieval comparison. This is only a common-budget **head** comparison; unequal encoder pretraining is not made equal.
4. **Calibration/safety** — fit temperature on calibration groups ONLY. Record top-label 15-bin ECE, multiclass Brier, full-denominator accuracy and class support, abstention, OOD false-accept rate at a **pre-registered** gate and old-task retention delta. No classification score replaces Final-use authorization. Independent future-window statistical acceptance is external.
5. **Resources** — run the optional `scale_reference.py` for real Python model cost, then run native `inference.control -> inference.worker -> neuron.runtime` on the approved target host at **64 / 256 / 1024 / 4096 logical Cell slots**, with separately declared simultaneously active counts and fully sampled load. Record p50/p95/p99, requests/s, actual process CPU/RSS, GPU peak, resident weights, cache misses, load/unload, adapter misses, queue/rejects, crash recovery, and privacy isolation. The reference Python script deliberately marks all records non-qualifying for native target-host closure.
6. **Lifecycle** — on the actual owner/store/host, fault-inject Artifact CAS write/read, signed load receipt, old-generation fence rejection, upgrade, restart and indeterminate dispatch/no duplicate execution, revocation/deletion nonresurrection and rollback checkpoint compatibility. Bind exact source/tree/model/weights/runtime/device, signed independent observer and real store witness to each case. The scorer checks *completeness*, not cryptographic signatures; only the independently governed owner may verify and accept native evidence.

## Commands on a clean, networked **model-capable** host

Prerequisites (use a separately locked environment): Python 3.11+, `numpy`, `huggingface_hub`, `torch`, `laya`, `sentence-transformers`, `psutil` and sufficient CPU/GPU/RAM/storage. Review code, license and all model dependencies before installation. The base repository's existing Rust tests must also be run with `just` per `AGENTS.md` on its Rust-capable builder.

```bash
# 0. Source-only preflight — no checkpoint download, no benchmark claim.
python3 -m unittest discover -v -s qualification/neuron-model-bakeoff -p 'test_*.py'

# 1. Input prepared by independent data owner: data.jsonl, queries.jsonl, corpus.jsonl.
# reviewed-shas.json contains 5 model keys mapped to inspected 40-char Hub commits.
python3 qualification/neuron-model-bakeoff/freeze_candidate.py \
  --template qualification/neuron-model-bakeoff/plan.template.json \
  --reviewed-shas reviewed-shas.json --decision-dataset data.jsonl \
  --retrieval-queries queries.jsonl --retrieval-corpus corpus.jsonl \
  --output /private/experiment/frozen-candidate.json
# STOP: Independently review all pinned bytes, host, dataset, thresholds,
# roles, future-window split, commercial licenses and security boundaries.

# 2. Five REAL reference model runs, by separately pinned checkpoint.
for m in laya_english laya_typed laya_multilingual arctic harrier; do
  python3 qualification/neuron-model-bakeoff/run_models.py \
    --plan /private/experiment/approved-plan.json \
    --dataset data.jsonl --model "$m" --device cuda \
    --output-dir /private/experiment/runs
 done

# 3. Independent retrieval test (raw reports must NOT be labelled native Hepta execution).
for m in arctic harrier; do
  python3 qualification/neuron-model-bakeoff/run_retrieval.py \
    --plan /private/experiment/approved-plan.json --model "$m" \
    --queries queries.jsonl --corpus corpus.jsonl --device cuda \
    --output "/private/experiment/runs/$m.retrieval.json"
done

# 4. Optional reference-only scaling evidence; not a native target-host receipt.
python3 qualification/neuron-model-bakeoff/scale_reference.py \
  --plan /private/experiment/approved-plan.json --dataset data.jsonl \
  --model laya_english --device cuda --active-cells 8 \
  --output /private/experiment/runs/laya_english.reference-scale.jsonl

# 5. After external native target-host resources and lifecycle receipts exist,
# concatenate 5 prediction JSONLs; assemble run-manifest.json mapping 5
# model keys to their generated .run.json; and retrieval results as JSONL.
python3 qualification/neuron-model-bakeoff/evaluate.py \
  --plan /private/experiment/approved-plan.json \
  --dataset data.jsonl --predictions /private/experiment/runs/all.predictions.jsonl \
  --runs /private/experiment/runs/all-runs.json \
  --retrieval /private/experiment/runs/retrieval.jsonl \
  --resources /private/experiment/runs/native-resources.jsonl \
  --lifecycle /private/experiment/runs/native-lifecycle.jsonl \
  --output /private/experiment/report.json
# Exit 3 means BLOCKED; exit 2 means INVALID. --allow-blocked is inspection-only.
```

## Gate semantics and known external blockers

`evaluate.py` never returns `accepted`, even for complete input manifests. Its terminal status is `BLOCKED` until independently verified native consumer signatures, role separation, longitudinal/future-window confidence bounds, explicit per-model resource limits, rollback and operator admission exist. Its model `execution_kind:real` identifies weight-backed **reference Python** execution only. A malicious JSON file could impersonate it; signatures/receipts and the actual independent evaluator are required for acceptance. No synthetic result, notebook score, mocked feature digest, developer CI green check or raw throughput test may bypass this limit.

Remaining blockers at initial submission: actual weight download and checksum review; independent task labels and frozen holdout; full Python/Rust stack on a suitable GPU host; real native model drivers/adapters; separate calibration/selection evaluator and preregistration; four native load profiles for each of five models; real Artifact CAS / Final-use / Generation Fence lifecycle receipts; security and licensing review; CI execution on exact candidate; supervised canary, independent acceptance and promotion/release. Missing evidence remains `BLOCKED`, never silently skipped.