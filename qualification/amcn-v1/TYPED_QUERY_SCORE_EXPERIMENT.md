# E3: source-first question-level scoring for typed MemoryCells

Scope: read-only research child of #1968 (stacked on #1777). This source does
NOT replace `amcn_historical_trial.py`, the original frozen LoCoMo archive,
existing HNMF/Neuron owners or the Reader. It is an independent *scorer*
that can consume an authentic upstream typed-Head run when such a run exists.

## Problem closed

The earlier E2 binary evidence-row accuracy can be misleading on extremely
imbalanced source candidates. A system can classify almost all irrelevant rows
as negative and still fail every full retrieval task. The correct primary
retrieval outcome is **per original question**, not per source pair.

`amcn_typed_query_score.score_query_support` requires:

- The original source-first `amcn_historical_trial.py prepare` public input
  (including frozen label-blind Top-16 sources and exact question/evidence
  bytes); caller-pinned canonical SHA256.
- A separately withheld original publisher-weak support inventory, bound to the
  exact frozen source-first plan; caller-pinned canonical SHA256.
- Every original non-TRAIN candidate prediction emitted by
  `amcn_typed_budget.train_typed_budget`, with complete frozen, single, typed,
  untyped and swapped-route physical output probabilities; exact digest pinned
  in the original training receipt.
- A pre-frozen complete case-to-functional-type inventory whose digest exactly
  reproduces the physical training receipt's original FeatureMatrix digest.

The scorer independently rebuilds the same canonical input digest as
`amcn_native.build_inputs` and
`experiments.shared_stem_cell.execution.Case.input_digest`, verifies original
source text hash, revision, scope/generation, read-only plan, lexical candidate
order, complete query/type/family/candidate census, publisher support/row-label
agreement and all five model-arm scores. A missing/duplicate candidate, removed
zero-hit question, altered training source, moved type or any invented answer
fails closed without producing a partial favorable result.

**Metrics:** lexically seeded source-first Top-1 vs all five physical Head arms;
per-question publisher-weak Top-1, Top-K availability and reciprocal rank,
by split/type, plus paired future-source-family win/loss/tie. Zero-support and
zero-shortlist-support questions always remain in the denominator. SOURCE-FIRST
Top-K is shared by every Head arm; learning an entirely new candidate generator
is a separate experiment. A post-hoc annotation match is not semantic
entailment, natural Reader completion or end-to-end memory compression.

## Executed evidence and still missing

The standalone stdlib CPU suite has 14 locally executed mechanism/adversarial
tests on explicit synthetic examples; see the dedicated isolated GitHub Action
for exact remote source. No original pretrained Encoder was loaded in this
child, no new LoCoMo public questions were answered, no strong hybrid RAG was
run, no true calendar future was observed and no independent human/issuer
qualification was obtained. Original `#1968` LoCoMo retrospective negative
result remains the relevant historical observation. This query-level score
should be run against **genuine, source-sealed original typed predictions**
before concluding typed specialization improves retrieval.

The external input SHA256 pins are integrity commitments, NOT cryptographic
proof of independent source ownership. This code cannot mint new signed
permissions or authorize Cell activation. Keep `production_accepted=false`,
Draft, and all original blocking-ci/Architecture gates unchanged.

## Local test

```bash
PYTHONPATH=qualification/amcn-v1 python3 -m unittest discover \
  -s qualification/amcn-v1 -p 'test_amcn_typed_query_score.py' -v
```
