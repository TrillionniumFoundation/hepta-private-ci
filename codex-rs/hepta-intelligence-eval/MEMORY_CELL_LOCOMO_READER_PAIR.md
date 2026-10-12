# LoCoMo fixed Qwen reader: frozen lexical k4 versus k8

Development-only actual-answer contrast. The previously published original source
cohort has 80 preselected LoCoMo questions, and the existing held-out proxy cut
has 16 evaluation questions from two conversation families. The original six
retrieval arms were committed as SHA-bound source-only selections before answers.
These questions are now exposed; none is a new prospective observation.

This experiment holds the **same immutable Qwen2.5-3B BF16 reader, prompt
template, 2,048 input-token limit, 64-token greedy decoder, original history and
lexical BM25 ranking** fixed. Only the number of delivered source turns changes
between the two already registered controls: lexical_k4 and lexical_k8.
Both source-byte totals and actual model prompt tokens/inference seconds are
measured. If a full source does not fit, that invocation is a recorded failed
attempt, not an automatic truncation or exclusion.

The generating job has physical access only to the original public-history and
six-arm-decision ZIPs (IDs 11728164433 / 11729394703). Its decisions must
reproduce the original 480 source-only rows. It persists all 32 actual Qwen
answers/errors and input receipts before a separate scoring job opens evaluation
answers (ID 11728856834). A generated citation marker is never attached,
repaired or reworded during scoring. Pinned outer ZIP checksums, exact source
byte/UTF-8 binding, model inventory, immutable generation commit, identity,
decoding budgets, and all question/arm attempts are audited.

Reported EM and token F1 are post-hoc **diagnostic**, not official semantic
adjudications. Publisher support IDs do not imply sufficient context. Citation
labels naming actually delivered sources are structural only; semantic precision
remains null. Actual failures and unscored questions widen all-planned effect
bounds. At two proxy families there is no statistically demonstrated reader or
memory advantage, and the reader is unchanged so any paired effect is
retrieval-context/cost, **not knowledge-parameter learning**.

Workflow: .github/workflows/hepta-memory-locomo-reader-pair.yml
Runner: scripts/memory_cell/locomo_frozen_reader_pair.py
No runtime owner, default adapter, production route or approval gate changes.
Production acceptance is false. A missing/queued or failed hosted run cannot
be relabelled a completed evaluation.
