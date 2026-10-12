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

## Auditable per-question cost and immutable generation boundary

A separate stdlib-only `locomo_reader_paired_cost.py` audit now validates
the complete **16-question / 32-condition** raw Reader census, the source
family proxy and the original lexical_k4 prefix of lexical_k8. It reports
the *observed matched-success subset* separately from k4-only success,
k8-only success, and both-failed questions. Extra actual rendered prompt
tokens, delivered UTF-8 source bytes and real generation time are recorded
per pair and per original evaluation-family proxy. A failed generation is
not assigned zero inference cost; latency excludes model cold load, and
UTF-8 bytes are not substituted for actual tokenizer counts.

Before the separate scoring job opens any evaluation-answer artifact, it
also validates the complete original raw JSONL against a byte-exact SHA-256
and every parsed row, including duplicate JSON-property and nonfinite
rejection. A required **externally supplied exact Git generating commit**
must match the immutable READY receipt; original public-input and frozen
decision ZIP SHA-256s, planned and actual logical attempt counts, success/
failure totals, model inventory and profile, generation/token ceilings,
and zero weight updates must be consistent. This validation executes with
no target labels, no pretrained model and no automatic source rewriting.

This is an audit protocol, not an observed paired Reader result until its
own exact-source GitHub Actions run finishes. The source cohorts remain
two published conversation-family proxies, not independently authenticated
unseen sources; semantic citation entailment, p95 production cost, dollar/
energy TCO and production acceptance remain unknown.

## Frozen k4/k8 paired quality-versus-cost interpretation (no promotion)

The evaluation is a **pre-existing 16-question / 32-condition paired
experiment**, not sixteen independent source families. The results may be
interpreted only once the frozen Reader has generated immutable raw outputs
and a separate scorer has opened the original evaluation labels.

`locomo_reader_value_gate.py` accepts only a **separately supplied,
externally SHA-256-pinned, complete original score report**. It reconstructs
the worst-case bounds over **all 16 planned questions**, cross-checks
per-arm scored denominators, the paired intersection, success/failure cost
counts, exact family-proxy matched rows, and actual prompt-token / source-byte
deltas. In fully observed pairs, the measured quality delta must also equal
the difference of the two complete, original arm means. A lower-priced
answer cannot be invented by excluding a failed model call or calling
delivered UTF-8 bytes "prompt tokens".

The possible descriptive results are (1) incomplete paired evidence,
(2) no positive all-planned QA delta lower bound, (3) an exploratory QA
difference with more actual Reader input tokens, or (4) an exploratory
QA difference without greater prompt tokens. **No case automatically
selects k8 or k4 as a serving policy**, and neither two public conversation
family proxies nor automatic token-F1 constitute an independent
generalization or a semantically adjudicated citation.

A new lightweight GitHub Actions workflow tests this gate with synthetic
counterexamples, **without loading Qwen, opening benchmark answers, running
retrieval, updating weights or triggering another expensive Reader job**.
The actual historical Reader result can be evaluated only after its
scored artifact exists and its SHA-256 is independently pinned. Missing
actual results are neither projected as zero cost nor called success.
`scale_out_permitted=false` and `production_accepted=false` throughout.

## Byte-locked literal answer accessibility before committing more Reader compute

Native document-ID support coverage is not sufficient evidence for a frozen
Reader: the exact answer string may be outside the delivered source text, may
require inference or paraphrase, or may be incorrectly annotated. The new
*source-only* `locomo_literal_answer_ceiling.py` diagnoses this boundary on
the identical 16 evaluation questions and the two original frozen lexical
choices (`k4` and `k8`), **without another model call**.

The auditor must first recover the two original, externally SHA256-pinned
public-history and frozen-decision ZIPs, reproduce the registered source order,
and persist a separately hash-bound 32-condition original selection plan.
Only **after that file is on disk** may it open the third, separately pinned
evaluation-target ZIP. It then reports source-ID support retrieval separately
from **literal occurrence of the published answer in any originally eligible
source**, any *selected* source and any *selected annotated support* source.

These are lower-bound **surface text accessibility** observations: an exact
literal match is not semantic relevance or entailment, and an absent literal
does not mean the source is insufficient (paraphrase, reasoning and multi-hop
questions may be answerable). Missing, unresolved or unanswerable targets have
their own denominators and are never counted as successful literals. No answer
string or original source bytes are exported in the final report; source-only
selection IDs and cryptographic pins remain available for provenance review.

This inexpensive control helps decide whether scarce BF16 model time should
be spent on retrieval/source-window improvement versus Reader capability.
It does not replace the original matched frozen Reader `k4`/`k8` run,
choose a serving policy, validate citation semantics, or authorize a
production rollout. `production_accepted=false` throughout.
