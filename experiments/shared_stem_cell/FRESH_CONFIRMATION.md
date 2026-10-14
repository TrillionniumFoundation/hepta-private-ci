# Frozen candidate, fresh confirmation, untouched final evaluation

The existing 32-record public holdout is exposed development material. This
increment does not tune another model against it. `fresh_confirmation` reloads
and hash-checks the existing original teacher bank, supervised shared Head and
both ridge candidates. The proposal is EXACTLY the earlier ridge calibration
choice, not the best observed holdout arm. It is locked before new acquisition.
All original fitters, selectors, studies and production boundaries are unchanged.

On the already qualified mmBERT/AG News revisions, select 1,024 public test
records: 512 confirmation, then 512 evaluation, in fixed salted-text-hash order.
Exclude every original producer text, including casefold/whitespace-normalized
duplicates, across both new phases. Full text remains <=768 UTF-8 bytes and must
fit the existing tokenizer ceiling without truncation. Keep the earlier public
smoke's alternating Cell assignment (256 rows/Cell/phase), not learned routing.
Missing records, changed sources or insufficient sizes fail without reselection.
This is content exclusion against the declared producer, NOT an assurance that
these sources were never used anywhere, writer/source-family independence,
pretraining cleanliness, or observations from a future time window.

Both phases' predictions for all four existing ridge-panel arms are sealed
BEFORE reading ANY new answers. Only confirmation labels can retain the proposal
or revert to the unchanged bank; they cannot select a different model, re-fit,
change regularization or tune a threshold. Seal that decision before accessing
final evaluation labels. Preserve all final outcomes, including regressions and
better unselected controls; never call a repeat on this fixed cohort a new test.

## Conditional paired nonregression calculation

For one frozen proposal on each Cell, let L count bank-correct/proposal-wrong
pairs and G the reverse. Its excess error is p_L-p_G. For each Cell compute a
one-sided Clopper-Pearson upper U_L and lower L_G, with tail alpha/(2*C), where
alpha=0.05 and C=2. A union bound yields p_L-p_G <= U_L-L_G simultaneously over
Cells, conditional on iid sampling within each Cell and a fixed proposal.
Neither independence between L/G nor between Cells is needed for this union
bound. Public-news dependence and deterministic cohort selection mean those
sampling assumptions are NOT verified here. All reports retain that limitation.

The empirical research decision keeps a strictly smaller proposal only when
ALL these upper bounds are <=0. No loss allowance is introduced. Zero observed
losses alone do not prove zero risk; a missing Cell never passes. The pure-Python
binomial-CDF inversion adds outward numerical padding and is tested against
independent direct sums and exact small-n coverage enumeration. Reference method:
SciPy `BinomTestResult.proportion_ci(method="exact")`, Clopper & Pearson (1934),
https://docs.scipy.org/doc/scipy-1.15.0/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html
This is conditional evidence, not production authorization or certified retention.

The existing pretrained CI lane runs the new command after consolidation, using
the same local verified Encoder snapshot. All 1,024 new rows require real encoding;
this is not a zero-Encoder-call claim. Reload, acquisition, Encoder load/forwards,
Head calls and confidence calculation are additional work. There are zero new
optimizer/SVD steps. No energy/FLOP/whole-process memory advantage is asserted.

```sh
python -m experiments.shared_stem_cell.fresh_confirmation \
  --study /qualified/public-study --consolidation /qualified/consolidation \
  --producer-sha256 <external-producer-report-sha256> \
  --consolidation-sha256 <external-consolidation-report-sha256> \
  --output /new/confirmation
```

Keep the output directory's lock, cohort, predictions, decision, outcomes and
failure logs together. It contains public source text, not anonymous embeddings.
The input Encoder/Head files remain unchanged. No CURRENT, new serving owner,
NDU subject or FinalUse authority is introduced.
