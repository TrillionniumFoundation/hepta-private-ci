# E1–E5 shared Stem causal study

Research-only, no production activation. This observational evaluator is stacked on the multimodal shared Stem research branch.

| Stage | Comparisons | Required external evidence |
| --- | --- | --- |
| E1 | Granite 97M, mmBERT-small, EmbeddingGemma 2 text; each vs no-change, frozen Head, learned Head | Real independent task labels, new source groups, OOD, retention and full cost |
| E2 | Cosine, from-zero Head, baseline residual 2K/8K/16K vs unchanged controls | Actual optimizer updates and held-out future improvement |
| E3 | text-only, OCR-only, unaligned, learned Bridge, native multimodal | Actual image encoder forwards, hard negative visual relations and independent sources |
| E4 | text-only, unaligned, audio bridge, temporal adapter, reversal | Real audio/video encoders, time-order counterfactuals and acoustic task utility |
| E5 | 64, 256, 1024, 4096 Cell cohorts, control vs shared Stem | Real host execution, active Cells, shared batches, cache behavior, p95/p99, CPU/GPU/RSS/energy and WAL recovery |

Use the common audit:

```sh
python experiments/shared_stem_cell/e1e5_causal_gate.py --observations /approved/study.json --output /sealed/audit.json
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e1e5_causal_gate.py' -v
```

Expected input schema: `hepta.stem-e1e5-causal-observation.v1`. Supply stage E1 through E5, immutable source/dataset/plan/evaluator SHA256s, Scope, independent source-group cases with split and chronology, one separately sealed probability per case per arm, claimed physical-forward status, and complete lifecycle resource fields.

The code checks elementary case parity, invalid cross-split reuse, future chronology, Reader evidence condition identity, missing arms, malformed cost reports and prediction sealing declarations. Its output provides descriptive Brier, accuracy and reported lifecycle times, not independent authentication.

**Research blockers:** Real weight loading and target-host forwards; teacher/model provenance; matched original no-change and frozen controls; genuine prelabel sealing, independent task outcomes and future chronology; full four-condition Reader adequacy including independently verified sufficient evidence and removed premise; sufficient grouped statistical power; real temporal pair verification; signed production receipts, authorization, crash recovery and exact-head CI. The tool does not independently authenticate model execution, labels, model origin, cost values or NDU. It always returns `production_promotion_permitted=false`.

Keep the work as a Draft research dependency; neither local synthetic tests nor workflow success establish a model winner or production acceptance.
