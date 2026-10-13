# Full shared Stem / Cell / System2 matrix

This is a research-only execution plan. It does not select a model, change the
production reader, enable NDU, or grant a topology mutation authority.

The matrix has 4 Stem rows, 4 Cell rows, 4 modalities, 4 inference rows and 3
structure rows: 768 complete configurations per Cell-count setting. The four
Stem rows are a small shared Stem, the existing shared 421M Stem, the shared
421M Stem with the dedicated Head budget, and replicated 421M models. Cell rows
are linear, gated, LoRA and sparse-expert. Modalities are text, image, audio
and video. Inference rows are no recurrent state, recurrent state, System2 and
System2 plus NDU. Structure rows are no split, offline split, and offline
split plus merge.

Every row records resource estimates for unique parameters, bf16 weight bytes,
active FLOPs and incremental Cell parameters. It reserves fields for task
score, evidence precision, unsupported-claim rate, ECE, Brier score, p95
latency, peak memory and energy. Empty metric fields are intentional; a plan
or a mechanics pass cannot be reported as model efficacy.

Before a neural row is admitted, an external `hepta.reader-gate.v1` receipt
must establish all four conditions: no evidence, ordinary retrieval, independent
human-checked sufficient evidence, and removal of the critical premise. The
minimum gate is 15/20 grounded-and-cited sufficient-evidence answers, a lower
ordinary-retrieval count, 18/20 exact refusals for each negative control, and an
independent adjudication flag. Missing or unverified receipts block every row
and preserve the complete plan without making neural calls.

The current repository research boundary remains unchanged: shared Encoder and
Head mechanics are implemented as candidates, while natural-language reasoning,
multimodal transfer, split/merge benefit and production acceptance require new
independent evidence.
