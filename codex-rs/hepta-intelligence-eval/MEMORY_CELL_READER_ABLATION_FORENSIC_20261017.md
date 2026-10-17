# Original reader capacity and premise-ablation forensic audit

**2026-10-17 · retrospective read-only audit of actual pretrained reader outputs.
Scientific disposition: no parameter-memory gain, no production qualification.**

The auditor retrieved the five *original* GitHub Actions ZIP artifacts registered in
`scripts/memory_cell/data/memory-reader-ablation-forensic-20261017.json`,
verified each outer byte-exact SHA-256 and all files against its embedded
`SHA256SUMS`, and compared original immutable raw answer journals to scoring
records. This was an actual local forensic pass on original generated outputs,
**not a fresh model inference or another training run**.

## Reader identity is a real confound

The SmolLM2-1.7B and Qwen2.5-3B reference runs shared the exact registered
eight-question plan `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`
and **48/48 identical evidence bundles**: same original selected IDs, raw
excerpts, derived views and bundle digests, same 2,048-token ceilings. Token
counts and real compute are not equal because their tokenizers and weights
differ. Every one of 48 attempted answers per model was archived before scoring.

| Eight authored task successes | SmolLM2-1.7B | Qwen2.5-3B |
| --- | ---: | ---: |
| Empty | 0 | 0 |
| Hybrid | 1 | 3 |
| Entity/time | 2 | 8 |
| Organized | 3 | 8 |
| Program support | 3 | 8 |
| Without prerequisite | 2 | 4 |

The matched organized-view difference is **five Qwen reader-only wins,
zero losses**, not a MemoryCell learning gain. The full-path entity/time
view also solves 8/8 for Qwen, so the more complex organizer adds
**zero** task successes above that strong nonparametric baseline.

The independently preserved Qwen 40-calibration/72-evaluation output archive
and read-only replay also pass the original SHA seals. Its eight test-arm
census is selected-k 5, Hybrid k=4 3, Hybrid k=6 2, reversed k=4 3,
single hop 4, entity/time 8, organized 8, program support 8, empty 0.
For the 32 case/arm pairs shared between the early Qwen experiment and the
later independent Qwen generation (empty, entity/time, organized, support),
the **raw answers are identical 32/32 and delivered evidence is identical
32/32**. That supports reproducibility of an authored cohort, *not*
statistical independence or prospective generalization.

## Ablation is not isolating an indispensable premise

Reading the original test labels (not a model-inferred gold) and the
**raw original evidence excerpts** delivered to each reader uncovers a
complete design confound:

| Task family | Number | Ablated evidence content | Qwen success | Smol success |
| --- | ---: | --- | ---: | ---: |
| Procedure / cross-experience composition | 4 | One retained original source, containing the exact gold answer literal as its **only site_/mode_ candidate** | 4/4 | 2/4 |
| New fact / correction | 4 | Zero delivered original sources; no gold answer literal | 0/4 | 0/4 |

The same treatment therefore changes (a) the purportedly necessary
relationship, (b) whether the answer is present at all, (c) source count,
and (d) task-family composition. A decoder can identify the single visible
answer candidate without proving it traversed the missing relationship.
Qwen answering 4/8 after premise omission **must not be scored as evidence
of robust causal reasoning or as a valid necessary-premise ablation**.
The corresponding literal-absent cases cannot distinguish retrieval failure
from reader inference either.

### Required next experimental correction

Separate two perturbations: **relationship-only removal** that preserves a
matched set of at least two plausible target values and equalized evidence
length/format; and **answer-bearing-fact removal** while matching unrelated
source counts. Independently review which relation is truly necessary,
freeze each evidence packet and labels *before* the reader runs, and audit
source roots/valid time. Use the stronger ordinary Hybrid and simple full-path
control with the *same* reader, prompt, tools and budget. Do not choose
the winner on these eight previously exposed examples.

## Auditability, economics and stopping rule

Original GitHub Action artifact IDs are **11669174727** (source),
**11674486085** (Smol), **11674741321** (Qwen), **11696514149** (Qwen
40+72) and **11696898778** (read-only replay). Full outer hashes, raw-journal
hashes, per-task source visibility and outcomes are recorded in the paired
JSON receipt. New explicit SHA-pinned source checks were executed locally;
the archived reply scorer was not retroactively relabelled.

The source cases are controlled and previously exposed. Human-reviewed
sufficient context, independent source families, prospective observations,
end-to-end raw source retention cost, revocation/recovery and matched real
program execution remain **unqualified**. This rules out promoting the
current learned candidate or treating a stronger decoder as parameter memory.
The subsequent prospective model experiment may proceed only after the
independent review and matched-ablation design are actually available.

Run the existing immutable replay admission
`scripts/memory_cell/reader_admission_gate.py` on the registered archives.
The separate `factorial_evidence_gate.py` now reports paired reader,
nonparametric and parameter contrasts and expressly refuses retrospective
development outputs as production credentials.
