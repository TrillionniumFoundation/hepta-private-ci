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

Every row records a nominal parameter budget and bf16 weight-byte calculation.
Active FLOPs, peak memory and energy remain null until a fixed workload is run
with actual route counts and a profiler or graph operation trace. It reserves
fields for task score, evidence precision, unsupported-claim rate, ECE, Brier
score and p95 latency. Empty metric fields are intentional; a plan or a
mechanics pass cannot be reported as model efficacy.

Before a neural row is admitted, an external `hepta.reader-gate.v2` receipt
must bind the same cohort, model weights, tokenizer, prompt, dataset, revision
and decode budget across all four conditions: no evidence, ordinary retrieval,
independent human-checked sufficient evidence, and removal of the critical
premise. The receipt must be checked against a separate trust manifest; a
boolean claiming independence is not accepted. The minimum gate is 75%+
grounded-and-cited sufficient-evidence answers, a strictly lower ordinary
retrieval rate, and 90%+ exact refusals for each negative control. Capability
bindings then decide which modality and inference rows can run. Missing or
unverified receipts block every row and preserve the complete plan without
making neural calls.

The current repository research boundary remains unchanged: shared Encoder and
Head mechanics are implemented as candidates, while natural-language reasoning,
multimodal transfer, split/merge benefit and production acceptance require new
independent evidence.


## Out-of-band review authority (required)

A self-declared reviewer list and a pair of hashes stored in the same submission
cannot prove independent human review. Before the planner can mark any neural
row as eligible, a separate trusted owner must establish the exact SHA256 of
the review manifest *outside* the submitted receipt and supply it via
`HEPTA_READER_TRUST_SHA256` or the explicit trusted-review argument. The
manifest itself must commit to the **entire** reviewed receipt content: cohort,
all four observed condition results, model/decoder/dataset binding, and
capability scope. Rebinding scores or replacing both the result and manifest
will not match that prior trust root. Malformed, duplicate or revoked reviewer
identities and unsupported capabilities fail closed.

No trusted review pin is currently provisioned in the ordinary research CI.
Therefore **all 768 configurations remain blocked by default**; a fabricated
positive unit-test fixture with an explicitly supplied test pin verifies only
the gate implementation, not actual reviewer identity or independent semantics.
A SHA pin is necessary but does not itself authorize a reviewer or validate the
underlying human judgments.
