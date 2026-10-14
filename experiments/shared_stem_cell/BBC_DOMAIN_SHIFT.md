# Different-publisher BBC domain shift: not a model qualification

This research-only probe reuses the frozen **same** public AG News
mmBERT-small, two Cell teacher Heads and consolidated shared/residual
alternatives. It does not train a new Encoder/Head, choose any winning arm,
change the production model, or silently rework the old research experiment.

## Source and preregistration

- Immutable source: \`SetFit/bbc-news\`, Git revision
  \`9c31f7087a8c225be8b4c420d70216ef1f121eb0\`, **test** split.
  BBC News articles date to 2004–2005; they may have been seen during
  foundation model pretraining and are **not** future evidence.
- Exactly 128 source examples are selected using a fixed SHA-256 rank over
  original article bytes, before reading any label, Head score or model result.
  Exclude exact casefolded/whitespace-normalized original producer and
  previously observed AG News texts, checking **both full source articles and
  their shortened 320-character model inputs**, not only the short excerpt.
  Keep exactly 64 cases assigned to each
  existing logical Cell via deterministic alternating route: that Cell
  assignment is a **proxy**, not an independently learned BBC specialist.
- Take the first 320 Unicode characters after whitespace normalization.
  This is an explicitly lossy **article fragment**, not the complete BBC
  document. Apply the identical fragment to all four Head arms. Never
  silently truncate the tokenizer's 512-token ceiling.
- Mapping is fixed before evaluation: \`business→AG Business (2)\`,
  \`sport→Sports (1)\`, \`tech→Sci/Tech (3)\`,
  \`politics→World (0)\` is an **approximation**. BBC \`entertainment\`
  has no AG counterpart; include it in the denominator for source support,
  but do **not** pretend it has a four-way ground-truth label.
  Unknown labels, source drift, invalid outputs or missing classes reject.
- Report frozen-model top-1 confidence on ALL unsupported entertainment examples,
  including counts above the **predeclared 0.80 and 0.95** thresholds and
  per-Cell counts, rather than silently discarding high-confidence unsupported
  outputs. Report proxy-label Brier loss only on the mapped categories.
  These are uncalibrated confidence diagnostics, **not** correctness on the
  fifth category, refusal ability or a calibrated OOD rejection threshold.
- The complete four-arm prediction table and label-free cohort are
  separately byte-hash-checked and sealed **before any BBC label lookup**.
  Tampered/duplicate/noncanonical files reject without calling the label
  accessor. Publish source hashes, names/indexes, per-arm proxy scores,
  unsupported coverage and actual Encoder/Head work receipts; **never**
  republish copyrighted BBC article text or model weights in Actions artifacts.

The label callback also re-reads each selected publisher record's **full
source article** and verifies its previously frozen SHA-256 before accessing
`label_text`. A changed article, missing category, or mismatched index fails
the entire research run; no category can be associated with changed evidence.

The post-seal preflight also requires the original **128 unique article
SHA-256s, unique excerpts and BBC source indices**, the exact
`bbc-news:test:<source_index>` case identity, and the original
`cell = sample_position % 2` alternation. It rejects a missing/extra
field, duplicated article or altered Cell route even when the attacker
recomputes both JSON file hashes. It contains no gold labels.

## Fifth precommitted virtual Head route, not post-hoc BBC selection

The original frozen panel executes **four physical arms**: bank, shared,
residual-corrected and standalone linear distilled. This study additionally
computes a **fifth virtual comparison**, \`shared_cell0_residual_cell1\`, using
the fixed AG-development routing hypothesis: Cell 0 takes the shared Head
probabilities; Cell 1 takes the shared+linear-residual probabilities.
The route is fixed in source before BBC sample labels are read and is recomputed
by the evaluator from the four archived probability matrices. Altering it,
dropping a parent arm, or selecting per BBC outcome invalidates the receipt.

For every eligible mapped BBC row, report paired **gains, losses, both-correct,
both-wrong** versus the unchanged Bank, including per-Cell discordance. The
unmapped entertainment category is excluded from four-way proxy correctness,
not from the source coverage/OOD confidence census. No choice is made among
five arms on BBC labels. This pairing is descriptive across nonmatching
ontologies, NOT a retention bound or a right to promote.

The fifth arm causes **zero additional model inference in this research
evaluation**, because all parent physical arms already executed. That does
NOT mean zero deployment FLOPs: real one-arm serving would require one shared
forward plus a residual forward on Cell 1 inputs, and its independent p95/p99,
energy and end-to-end cost are **not** measured here. Report the four-arm
research work separately from any hypothetical serving portfolio.

The evaluator performs five-arm tensor-shape/probability/route validation
BEFORE accessing even the first BBC category label, including if a caller
has recomputed the file's SHA after substituting a favorable arm. The
existing full AG News confirmation and sequential execution run first in
CI; a BBC-source outage/ontology failure must not hide their retained
completed results. A BBC failure is still a failure, not a skipped pass.

## Full-publisher source-selection replay, not just row validation

The source identity rules now also recompute the fixed 128-row SHA ordering
from **all 1,000 BBC test article texts** and the previously pinned AG
exclusions. Before the first model forward, the complete text-column
digest, old-text exclusion digest, exact 128-case order and alternating Cell
inventory are written to a separate \`publisher-selection.json\` receipt.
After the frozen model has run but **before reading any category**, the same
complete text column and original exclusions are replayed and the receipt is
SHA-checked again. No category column is consulted by this control.

A rehashed 128-row index can be structurally well-formed while substituting
a convenient article or permuting two same-Cell entries. Such indices now
fail the full-source replay even if every identifier, digest, case/index
binding, Cell parity and five-arm probability file has been rehashed.
Synthetic adversarial tests exercise both cases, changing unselected
publisher text and changing earlier exclusion data. A digest is still not
proof of publisher authenticity, independence from pretraining or a
future-window model improvement.

## Independent publisher-source job

\`bbc-public-source-admission\` runs in a separate small, pinned Python
environment and checks the real immutable BBC test split **without a model**.
It retrieves the original SHA-pinned pretrained archive, verifies 128
producer and 1,024 prior confirmation/evaluation source texts, then
computes the full 1,000-row BBC text-column SHA and exactly 128 fixed
source selections. Only hashes and source indices are uploaded, never
original articles or labels. This isolates publisher/API and source
provenance failure from the full pretrained or browser CI. It does not
verify capability, new model inference, future independence or energy.

## Valid and invalid claims

Different **publication family** offers a useful domain shift. Its label
ontology, article length, source era and task framing differ from original
AG News. Thus accuracy on its mapped subset is **descriptive diagnostic
agreement**, not a controlled same-task generalization estimate, clean
holdout, unbiased Cell-retention certificate or future-window performance.
No winning arm may be selected on these evaluation labels. All receipts
retain \`same_label_ontology_verified=false\`,
\`pretraining_clean=false\`, \`retention_certified=false\`,
\`external_independent_model_gain_proved=false\` and
\`production_accepted=false\`.

Existing \`sequential_work_audit\` validates the whole physical Census for
the original Bank, shared, corrected and independent-linear alternatives.
The Head study necessarily executes **all four arms**, so summed actual
work is the experiment's workload, not the cost of choosing a single arm.

Run with the existing public-pretrained-smoke outputs:

\`\`\`sh
python -m experiments.shared_stem_cell.external_bbc_shift \
  --study /path/hepta-public-study \
  --consolidation /path/hepta-consolidation \
  --producer-sha256 "$PRODUCER_SHA" \
  --consolidation-sha256 "$CONSOLIDATION_SHA" \
  --previous /path/hepta-fresh-confirmation \
  --previous-sha256 "$PREVIOUS_REPORT_SHA" \
  --output /new/path/hepta-bbc-domain-shift
\`\`\`

The independent GitHub Actions result—not fixture tests alone—must finish
on the **exact current HEAD** and preserve original failure.json for any
dataset acquisition, parser, model import or resource-budget failure.
