# E1–E6 final Stem selection: research-only paired screen

This is a **non-authorizing** downstream screener for Hepta Shared Stem/Cell
experiments. It does not load a model, train a Head, verify a signature, execute
physical Cells, certify a target host, or select a production artifact. It
expects independently produced and sealed observations. **No complete qualifying
real-data bundle was supplied or produced in this delivery.**

## Source and experiment producers

Feed real outputs from `execution.py`, `head_batch.py`, `paired_frontier.py`,
`qualification/neuron-stem/statistical_gate.py`, multimodal/temporal ablations
and the production owner's target-host scale traces. Converting those existing
receipts to a bundle requires an independent join on case/input/source/scope;
this component intentionally cannot supply or fake missing observations.

- E1 must include **mmBERT-small / Granite 97M R2 / ModernBERT-base / mmBERT-base**.
- E2 must include 2,048 / 8,192 / 16,384 / 65,536 / 262,144 Head budgets.
- E3 must include joint and shared-feature plus Cell-state fusion.
- E4 must include V1 / V2 / V3 / diagonal SSM / low-rank minGRU.
- E5 must include text Stem + Organ vs EmbeddingGemma 2 on identical tasks.
- E6 must include actual 64 / 256 / 1,024 / 4,096 Cell host counter traces.

The `coverage` digests are references to externally audited results, not an
execution claim. Every preregistered arm must include exactly the same
future_1/future_2 cases, input SHA, source group, event timestamp and old-task
membership; failed/abstained cases remain in the denominator. The Stem is frozen,
model revision is a full 40-hex commit, and tokenizer/Head/Stem are SHA-bound.
`baseline=no_change` and all arms share registered training steps and seed.
Outcomes must occur strictly after the declared freeze and future_2 after
future_1, with 30+ reported source groups in each window by default.

## Statistic and decision

For each candidate, form within-source-group mean differences against no-change
on **external** future net decision utility. Resample reported source groups with
replacement separately within future_1 and future_2. Each window must have a
positive one-sided LCB at alpha=0.05/(2 × number of preregistered candidates),
and the candidate is ranked by its worse-window LCB. Worst-window old-task
negative transfer also must pass. It is a conservative **exploratory cluster bootstrap**, not a
finite-sample proof: independent source identities are not authenticated by this
reader. The screen also rejects negative transfer, Brier/ECE/OOD/old-task
regression and any breached p99/RSS/GPU/recovery hard threshold.

If every claimed E1–E6 experiment is complete, the required candidate families
are observed, source-group counts pass, paired LCB is positive, and quality and
physical resource caps pass, the screener may return
`provisional_research_leader`. This is **not** a model winner because the
following remain hardcoded `false`: production accepted, model selection
authority, preregistration authenticity, independent groups, observer signature,
real model execution verification and target-host attestation. A separate
independent Evaluator, Selector and effectful Executor must remain distinct.

## Commands

```
python3 -m unittest -v experiments.shared_stem_cell.test_final_selection_gate
python3 -m experiments.shared_stem_cell.final_selection_gate \
  --bundle /approved/externally-sealed-e1-e6.json \
  --output /scratch/e1-e6-shadow-screen.json
```

`test_final_selection_gate.bundle()` is a **synthetic fixture only**; the
published smoke input uses `origin=fixture`. Even deliberately relabeling it
`measured` does not authenticate its rows. Do not record fixture-derived positive
statistics as model or production results.

Run from repository root. Missing metrics do not become zeros, missing arms do
not become competitors, and this CLI cannot access production routes.
