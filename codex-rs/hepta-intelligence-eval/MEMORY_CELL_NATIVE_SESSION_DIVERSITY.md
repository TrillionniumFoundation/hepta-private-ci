# Native session diversification: separate evidence diversity from authority roots

## Source-pinned negative result from the previous root-diversity ablation

The original completed frozen retrieval grid generated at
`1e11b9af3ca2f518cbc492ee5198ed08994d670b`,
[Actions #38132302474](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38132302474),
artifact `11700210642` (ZIP SHA-256
`f41cc4df803eddf6c502ea3137b0385374464ac4d8869bc07b143362aa9329fe`)
contains 80 label-blind source rankings and their post-selection weak-label report.
The outer ZIP digest and original internal JSON were inspected.

The original root diversity changed **0/80** top-eight source sets and had
**zero** weak document/window rescues. All **72 LoCoMo** tasks had only one
distinct withdrawal/provenance root across their **top 64** candidates. Their
original top-eight had seven duplicate-root slots per task. The eight
LongMemEval tasks had 43–62 distinct roots in their top-64. For LoCoMo, every
conversation turn inherits one source-family trust root, while native
`Document.session` distinguishes actual dated sessions. **A provenance
root is not a useful diversity unit there.** It must remain the revocation
and history/citation authority, never be rewritten as a session identity.

## New matched research-only control

Keep the same already-indexed native corpus and strict as-of cut; use the
same pinned MiniLM encoder, the original frozen `k64/lex0.50` RRF ranking,
eight delivered documents, `WindowBudget`, source scope and question.
The existing top-64 ranked set is reused without extra retrieval or model
forward passes. The new ablation first takes the highest ranked candidate
from each **actual original `Document.session`**, then fills remaining
slots from the original rank order; the first-ranked original item stays
first. Roots, IDs, dates, citations and revocations are left untouched.

The 80 session-selected source sets, including all 48 TRAIN and 32
selection/retention/test/transfer questions, must be persisted to
`session-diverse-label-blind.jsonl` **before** source labels are read.
Original RRF grid, root-diversity, TRAIN-only retrieval calibration and
raw source windows remain unchanged. A separate
`session-diversity-weak-source-diagnostic.json` reports both rescues and
regressions against identical original top-8 results, including unscored
native labels and available session counts. A changed source does not
automatically mean an answer improvement.

This study remains exploratory on an **already exposed** native task panel.
Weak native support membership is not independent semantic entailment.
Session diversity must not be adopted as a learned gain, stronger RAG
superiority, citation-quality certification, prospective-window observation,
or production result. Before adopting it as a retrieval default, require
newly admitted source families, same-reader/same-tools and matched budget
answer evaluation with independent evidence sufficiency review.

Reproduction is via the unchanged pinned native input, original complete
strict-as-of archive and scoped
`.github/workflows/hepta-memory-stem-frozen-retrieval-grid.yml`.
No reader weights, training schedule or acceptance gate are modified.
