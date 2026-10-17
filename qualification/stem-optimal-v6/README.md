# Hepta Stem V6 — train-only 4-fold calibration of cheap original controls

**DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO MAIN / NO FINALUSE / NO CELL SPLIT.**

Frozen parent V5 PR #2623 at `db7ff94f49f6ffe082b8d4f667a0e33fe65555e8`.
This V6 is additive. The V3/V4 original 96 public cases, original prediction
archives, source locks, candidate model weights and training program remain
unchanged. V3 + V4 independent original-label reviewers have succeeded, while
V5 six-archive original independent paired review has separately passed
in GitHub Actions #39016413565; its historic result does not validate V6.

The original 32-case V3 fee/charge result gives Granite47 30/32 correct with
both the trained Head and the cheap **same-Encoder** centroid; no learned Head
incremental correctness has been demonstrated. The original V4 fixed-
`temperature=8` word and character TF-IDF controls have 25/32 and 27/32.
Comparing fitted neural probabilities against *untuned* cheap cosine softmax is
not enough to establish better calibrated learning. V6 specifically isolates
this loophole. The original TEST label cohort was **previously inspected** in
V4 exploratory work; V6 is strictly retrospective, not prospective confirmation.

## Frozen protocol

- Original 64 published TRAIN text/label pairs, original 32 TEST texts without
  labels, immutable V3 `source_plan_sha256` and both publisher CSV SHAs.
- Per class, 16 TRAIN observations sorted by SHA256 of a fixed V6 salt and
  source ID, assigned round-robin to 4 folds. Each fold validates exactly
  4 cases/class (16) while only 48 others construct its vocabulary, smoothed
  IDF, supervised class centroids and cosine predictions.
- Fixed temperature candidates: **0.5, 1, 2, 4, 8, 16, 32**. Choose the one
  minimizing mean 4-class Brier over the 64 strictly out-of-fold TRAIN
  predictions, ties resolved by the smaller temperature. **No TEST label is
  used for this choice, vocabulary, IDF, class centers or preprocessing.**
- Refit class IDF and centers on the complete 64 TRAIN cases using the chosen
  temperature. Emit 32 case-linked TEST probability vectors, immutable fold
  assignments and all CV losses. Record measured process CPU/wall/RSS, null
  power/p99 and **zero** neural forwards, all authority false.
- A separate read-only source owner consumes the true original V4 immutable
  ZIP. A separate producer fits the new cheap models; only after sealing those
  unlabeled predictions does the independent reviewer reacquire the exact
  original publisher labels, compare old V4 fixed-T=8 receipt, independently
  replay all four fold fits and 32 predictions **without importing the V6
  producer**, and score mean Brier and correct counts.

A positive softmax temperature cannot change the top-class ordering for a
fixed cosine vector, so V6 is a **calibration-control experiment**, not an
accuracy-improvement experiment. If the train-only selected temperature lies
on the upper grid boundary, report it honestly rather than extending the
search after inspecting TEST outcomes. Calibrated Brier can improve or worsen;
no outcome permits autonomous Stem selection.

No new source family, future time window, no-change deployed 421M matched
lifecycle, negative transfer, independent NDU utility, target-host scale or
signed FinalUse is supplied here. Preserve original experiment dates and
retrospective exposure disclosure. 

Source-only checks:

```sh
python -m unittest discover -s qualification/stem-optimal-v6 -p 'test_*.py' -v
python -O -m unittest discover -s qualification/stem-optimal-v6 -p 'test_*.py' -v
python -m py_compile qualification/stem-optimal-v6/*.py
```
