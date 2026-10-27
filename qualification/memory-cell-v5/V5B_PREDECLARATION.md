# V5b: one bounded, predeclared negative-subclass revision

This revision is authorized only after the disclosed V5a development failure.
The independent new V5 held corpus has not been read. V5a's 12 fits, six-candidate
configuration, predictions, calibration traces and available byte-identical
execution-source snapshot remain unchanged in their original directories.

## Mechanism and exact two added candidates

V5a fits one `__reject__` class to heterogeneous negative requests. V5b tests
whether separate learned negative regions improve the observed coverage/risk
tradeoff. It adds exactly these two candidates:

- `word-lr-c4-negative-families`: original word 1–3 gram feature configuration,
  multinomial logistic SAGA with C=4, maximum 2,000 iterations, tolerance 1e-5.
- `mixed-svm-c2-negative-families`: original word/character feature configuration,
  linear SVM with C=2, maximum 2,000 iterations, tolerance 1e-5.

The original 840 positive and 810 negative training texts remain byte-identical.
There is no new data augmentation or label inferred from held queries. Existing
training `family` metadata supplies the following five negative subclasses:

| Existing training family | Negative rows |
|---|---:|
| `different-window-or-alignment` | 360 |
| `generated-ordered-operand-contrast` | 64 |
| `manual-near-ood` | 42 |
| `unsupported-statistic-or-output` | 288 |
| `wrong-address` | 56 |

The six supported classes remain unchanged, giving 11 learned output classes.
The taxonomy comes from the original V5a training generator, not the independently
authored held metadata or a new phrase list. No negative family is selected by a
runtime query rule: inference uses the learned coefficients on n-gram features.

Each training example retains its original seven-class balanced weight. All five
negative subclasses therefore use the original unified-reject per-example weight.
Balancing eleven classes independently would increase the total negative weight
from 1/7 to 5/11; that confound is deliberately excluded from this candidate pair.
All actual class weights and output-class counts are retained in fit receipts.

For the external seven-class contract, preserve the six learned positive scores
and use the maximum learned negative-subclass score as the unified reject score.
This exactly preserves the raw 11-class argmax decision after mapping a negative
winner to `__reject__`. Softmax of these mapped scores is used only as a normalized
decision score, not a calibrated probability. Full 11-class scores and the winning
model label are retained in every V5b decision trace.

## Selection, execution and stop rule

The same 121 calibration pairs and original selection rule apply. Correct known
acceptance must still reach 80%, with OOD false acceptance at most 5%. There is no
change to the support/rejection definition, selection corpus or diagnostic corpus.

This development increment runs exactly two candidates × seeds 8011 and 8017:
four new fits. It constructs only the actually needed word and full-character
feature caches, records their actual CPU/wall/storage/array cost, and retains
every new candidate. Public selection metrics can be compared with the six
retained V5a candidates using the unchanged primary selector. No candidate is
evaluated on independent held language by the training owner.

The training source, public-corpus digests and this declaration are captured in
`validation/routing-v5b-predeclared-source/PREDECLARATION.json` before fitting.
There will be no third repair family in this research increment. Once these
four fits and their mechanism checks are recorded, source/configuration freeze
and root-controlled formal execution of all eight candidates may proceed. The
formal seeds 1019, 1021, 1031, 1033 and 1039 remain reserved for that frozen run.

## Scope

A better result would support only this bounded, author-synthetic English routing
contract. It would not establish general semantic understanding, production-safe
OOD detection, unrestricted memory composition, or restoration of V4 evidence.
