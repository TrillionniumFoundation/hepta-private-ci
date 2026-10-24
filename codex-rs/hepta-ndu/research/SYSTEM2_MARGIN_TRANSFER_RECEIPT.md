# System2: one-sided margins do not resolve this transfer failure

Parent: `cdd1901a8d15bdfbc8c27747659216474f8922b4`, PR #1546.
This stage changes neither production/default policies nor NDU/FBSDE definitions.

## Prior full-repository execution is now verified

Run **38150783742** completed successfully for parent `cdd1901a...`, tree
`54f3a58fb9b5d1636eea19bc0b625afd681baa9c`. Artifact **11705874648** is
203,279 bytes, ZIP SHA256
`1b09d6c98201118e0a01fa741bbe094aa8aa476a80fa9a84b3c10b4018528566`.
All **92 manifest entries / 93 files** verified. The full regression log records
**996 passed, two skipped, 998 total**, not 998 passes.

All **32/32** original linear-replay conditions succeeded. Their aggregate scores,
per-question decisions, raw/centered records and pair accuracies exactly match
the prior local observations. This is a full-repository torch 2.5.1 replication
on the same cached training features, not an independent cohort. The original
`stop_no_cross_family_source_gain` conclusion remains. No new Encoder or Reader
was invoked. Historical outputs are not relabelled as this stage's generation.

## Hypothesis fixed before this stage's local candidate run

The old objective penalizes both margins below one and margins above one. It can
therefore pull already sufficient frozen positive/negative gaps down to one.
This stage tests a one-sided loss, with the SAME pairs, question weights, margin
one, regularization **0.01**, top-four proposal and family/root-disjoint folds:

`J(w) = ||relu(b - A w)||^2 + 0.01 ||w||^2`.

Only existing linear StemHead readout weights (384, of 770 total parameters)
adapt. Frozen null weights and common bias remain unchanged. No regularization
search, alternative encoder, new benchmark labels or post-result mode selection.
Methods: frozen, original ridge, squared hinge, and erased-residual-input hinge.
Erasure preserves native frozen logits; it does not erase the reference itself.

The bounded nonnegative dual uses `H=A A.T+lambda I`, `w=A.T alpha`, and checks
`alpha>=0`, `H alpha-b>=0`, complementary slackness, and primal stationarity.
An active-set limit fails explicitly; every factorization size is recorded.
Tests compare small problems against exhaustive active sets and autograd.
An initially sufficient pair may become active while another pair is corrected;
the solver does not simply delete all initially correct pairs. This objective
does not guarantee retention on arbitrary training pairs or unseen questions.

## Separate source ranking from stopping

Three recorded views share the SAME fitted weights and evidence ranking:
raw logits, the inherited mean-centered residual, and `frozen_stop`.
The latter keeps the empty/nonempty decision entirely on the frozen native
maximum score (threshold zero), then uses the fitted ranking when permitted.
It can still abstain when the frozen score is nonpositive. Held-out labels do not
choose this gate. It is the fixed primary comparison, selected before results.

Frozen-stop is NOT a newly learned or calibrated abstention policy. It prevents
an arbitrary learned score origin from changing this control's abstention, but
cannot establish evidence sufficiency, task correctness or NDU terminal utility.
No view is installed as a default serving policy. No Reader answers are generated.

## Observed local cached-native result

All **32/32** conditions completed, zero failures, zero new Encoder/Reader calls.
At the final capacity cut, 20 of 35 pair rows had frozen gaps already at least
one. The new hinge fit selected 19 active constraints. At cuts 16/32/48,
centered/frozen-stop training source hits were **3/7, 6/14, 10/20**, compared with
original ridge **3/7, 6/14, 11/20**. Hinge training singleton pair accuracy was
1.0, 1.0, and 0.969697; these are weak TRAIN-source metrics, not QA accuracy.

On the same five leave-family-out refits:

| Method | Raw hits / empty | Fixed-stop hits | Family-macro hit rate | Pair question macro |
| --- | ---: | ---: | ---: | ---: |
| Frozen | 6 / 0 | 6/20 | 0.280000 | 0.734848 |
| Original ridge | 0 / 20 | 6/20 | 0.246667 | 0.727273 |
| Squared hinge | 1 / 14 | 6/20 | 0.246667 | 0.727273 |
| Erased hinge | 6 / 0 | 6/20 | 0.280000 | 0.734848 |

Compared with frozen, hinge changed seven fixed-stop selections, with **one
source hit gained and one lost** in different families. Nine no-pair-opportunity
questions remain counted. Five source families, not 35 pair rows, describe the
recorded grouping; this is reused, exposed TRAIN data, not independent evidence.
Disposition: **`stop_no_nonregressing_cross_family_gain`**. Fewer raw empty choices
are not a transfer gain and do not establish improved rejection calibration.
The tested one-sided correction did not resolve this failure; this does not
prove that any single defect is the unique cause or a general model limit.

Across 16 local hinge/erasure conditions there were 226 attempted factorizations.
Maximum dual KKT residual was approximately 1.18e-14; maximum primal stationarity
residual approximately 2.98e-15. These certify numerical checks for the declared
finite objective, not semantic correctness or an FBSDE existence theorem.

## Reproduction and evidence boundaries

The four new/changed paths add a research script, 16 tests, this receipt and one
additional step in the existing workflow. The original full regression discovery,
static diagnostics, immutable artifact audit and 32-condition linear replay are
preserved. Hosted execution adds 32 margin conditions; it does not skip failed
conditions or stage another pretrained model. Actual costs are not claimed equal.

Local **111/111 System2 tests** passed, including the actual pinned archives and
16 new numerical/protocol/runner tests. The local environment is torch 2.10.0+cpu,
safetensors 0.7.0, and source-overlay modules with verbatim repository dataclass
and StemHead constructor/forward ports. Full-repository execution is separate.
Local `just`/Ruff are absent and network name resolution is unavailable; no Rust
source changed and no repository check is waived. Python compilation passed.

```sh
export HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD)
python scripts/memory_cell/system2_margin_transfer.py \
  /path/to/system2-content-38147248105.zip /new/margin-output
```

The output plan fixes the protocol before loading labels. Per-condition state,
reload checks, source roots, solve counts, all three views, gains/losses and
failures are retained. Local `source_commit` is explicitly labelled as the source
OVERLAY PARENT, not the generating Git head. Hosted runs use the actual head SHA.
Human sufficient-evidence review, outcome-calibrated stop/continue values,
independent transfer, multimodal ability and production acceptance are unestablished.
