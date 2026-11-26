# Frozen reader capability before further MemoryCell training

This opt-in experiment preserves HNMF evidence, authority, version and recovery
owners. The old single-window and LoRA experiments remain unchanged. These new
Python projections are not registered production wire types or another Memory OS.

## Executable changes

`evidence_bundle.py` constructs UTF-8 byte-exact windows over the entire admitted
source view at index-build time, rather than always truncating a source prefix.
Indexing is bounded to 8 MiB/20,000 windows and charged explicitly; reaching the
limit rejects the complete build rather than hiding the tail. The existing
scope-isolated persistent FTS5/dense index is reused for query-time retrieval.
Each bundle carries original IDs, roots, scope, observation time, offsets, original
content digest and source frontier. All fragments are revalidated before and after
reader inference. A future observation rejects; observation time alone never
proves semantic valid-time, fact supersession or independent observation.

Ranked-list selection is compared with a fixed marginal-query-term-coverage and
redundancy heuristic on the SAME initial candidate list. The supplemental variant
has at most three reads of 32 candidates, using uncovered query vocabulary only.
These are transparent non-learned policies: lexical coverage is NOT semantic
sufficiency. More rounds and index building are not free. Both policy and reader
training are deliberately paused until capability/coverage diagnostics identify
a useful target. Future learned selectors must beat these exact frozen controls.

`bundle_reader.py` delivers up to eight exact sources to ONE frozen reader. It
measures the full chat prompt and rejects overflow without trimming source bytes.
Every empty-context control also calls the reader. Answers and citation markers
are not repaired after generation. The existing unsigned citation audit records
bind the actual delivered fragments; structural labels are not semantic judgments.

## Frozen diagnostic matrix

Planning runs once before any reader output. Native questions are selected in
fixed hash order (default two per LongMemEval/LoCoMo), plus two separately reported
AUTHORED controls requiring multiple facts/time or procedural composition. These
controls are not actual build observations, real future events or independent
human annotations. All native cases are public development, not fresh holdouts.

Twelve conditions per case include single window; ranked and coverage sets of
2/4/8 windows; bounded supplemental retrieval; the same four-window bundle with a
larger token cap; empty context; all publisher-annotated sources; and one removed
publisher source when possible. Most arms allow 2,048 prompt tokens; full-source
and larger-budget diagnostics allow 4,096. Generation is fixed at 64 tokens.
Budget ceilings need not be fully consumed; actual token counts are reported.

The full-source condition is **publisher support only**, NOT an independently
confirmed complete oracle. All cited original sessions are retained without
answer-aware trimming. When an entire session cannot fit, it is explicitly
`unavailable/complete_context_exceeds_budget` with required and allowed tokens.
When annotations are absent/unresolved or too numerous, the condition is likewise
unavailable. These cases stay in every denominator and uncertainty bound. The
removed-source intervention does not relabel an answerable real-world question as
unanswerable. Truly human-confirmed minimal sufficient spans still need independent
review and existing admission; no new signature or completeness claim is issued.

Three read-only SmolLM2 tiers are pinned by exact published revisions: 135M, 360M,
and 1.7B. All receive the same precomputed conditions, prompt policy and decoder.
They are diagnostic capacity tiers, not a claim that 1.7B is qualified or adequate.
Within-reader comparisons separate evidence organization and budget effects;
changing reader size is never counted as a learned memory benefit. No reader is
automatically selected or deployed based on this exposed small development set.

## Evidence and interpretation

Original raw answers are synced before the separate answer-label file is opened.
Operational failures still fail the run, after retaining the complete report.
Unavailable oracle/budget conditions do not become model errors or success scores;
coverage, failures, all-planned bounds, answerable/unanswerable strata and source
family uncertainty remain separate. F1 is diagnostic, not official semantics.
Source-identity recall is not sufficient-evidence coverage. Zero markers yield no
semantic precision result. All outputs retain `production_accepted=false`.

Artifacts retain the source/model/data identities, index costs, actual token use,
process resource receipts, all original sources and raw/scored answers. No new
weights are trained. Model tensor files are referenced by full pinned inventory,
not reuploaded per run. The small lab scope is not a full new native benchmark.

## Reproduction and remaining work

Run `python3 -m unittest discover -s scripts/memory_cell -p 'test_*bundle*.py' -v`
for focused mechanism tests; the hosted workflow also executes the whole Python
suite and repository `just fmt --check` before staging the experiment.

`bundle_trial.py plan STAGED NEW_PLAN --limit 2` builds the immutable experiment.
`bundle_assets.py stage TIER NEW_MODEL` stages exact public models before offline
execution. `bundle_trial.py run` requires the externally supplied plan and label
SHA-256 pins. `bundle_assets.py collect` rejects a missing model tier or changed
plan/model identity. See `.github/workflows/hepta-memory-bundle-diagnostic.yml`.

Next experiments must use reviewed minimal-sufficient evidence, realistic temporal
and multisource supervision, and observed executable procedural outcomes. Learn
only after a shared reader demonstrates useful oracle capability. A prospective
stream must freeze its learned state before future query exposure and report
write/train/read/retention/revocation costs; this diagnostic has no optimizer and
creates no learned snapshot or real future observation. Independent acceptance,
production cutover and >=99% semantic citation qualification remain unchanged.
