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
  previously observed AG News texts. Keep exactly 64 cases assigned to each
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
- The complete four-arm prediction table is sealed **before any BBC label
  lookup**. Publish source hashes, names/indexes, per-arm proxy scores,
  unsupported coverage and actual Encoder/Head work receipts; **never**
  republish copyrighted BBC article text or model weights in Actions artifacts.

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
  --output /new/path/hepta-bbc-domain-shift
\`\`\`

The independent GitHub Actions result—not fixture tests alone—must finish
on the **exact current HEAD** and preserve original failure.json for any
dataset acquisition, parser, model import or resource-budget failure.
