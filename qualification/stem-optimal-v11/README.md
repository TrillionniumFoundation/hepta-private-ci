# Hepta shared Stem V11 — fit-only online conditional computation

**Draft / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / no main merge, model promotion,
FinalUse or Cell Split.** Immutable exact parent V10 #2700
`611cb4ce297ca9339345590fcd25fce5a19dddef`.

## Why V11

The V8 route chose exactly 8/32 cases by ranking the **entire** 32-case TEST
batch. That is not an online policy for desktop, mobile or interactive agents:
it needs future requests before deciding on the current request. V10 physically
compares batch-8 to batch-32, which tests possible conditional compute but not
an independently trainable confidence threshold. V11 closes this logical gap
with a *TRAIN-only* threshold, not a top-K of the TEST batch.

Only 64 original BANKING77 FIT texts and labels assign four label-stratified
folds (16 FIT rows per fold). Each validation row receives a trained-on-48
**char 3–5-gram TF-IDF centroid** prediction with fixed T=8. Out-of-fold
margin = top1 probability minus top2 probability. Sort the **64 FIT OOF
margins**, choose the midpoint between 16th and 17th: nominal 25% TRAIN
escalations. Duplicate boundary is fail-closed. The complete original 64 FIT
rows then build the frozen cheap classifier for later TEST requests. Each
new request may be routed independently based on **only that request's**
cheap margin against the frozen threshold; no TEST sample count or future
batch ranking determines eligibility.

There is **no cap of exactly 8/32 TEST cases**: future escalation count may
be 0, 32 or anything between. On the immutable historical cohort, original
publisher V3 and V4 source JSON / V4 probabilities were reopened in the
analysis container with original ZIP SHA locks; an exploratory recheck made
**7/32** independent online escalation decisions at threshold
`0.1252547339252062`. This is not physical pretrained inference or a
prospective outcome. Every published case must re-match old original V4
character probabilities to `1e-12` and original V5 source SHA.

## What this does NOT prove

- The 32 public TEST labels were previously exposed during V3–V10. The
  routing rule was chosen *after earlier results*, so it is research-only,
  not a new blinded holdout or statistically confirmatory observation.
- This stage executes **zero** pretrained Encoder forwards and does not
  reduce model loading, original 64-FIT encoding, learning, CPU/RSS, p99,
  energy or full lifecycle cost. All savings fields are explicitly false.
- Later real physics must run **only the threshold-selected K inputs** in
  a genuine original pinned Transformer, compare numeric parity to the
  historic full-paid V3 result and account for all fit/cheap/load costs.
- A new source family, genuine future timestamped test, independent
  evaluation, negative transfer, NDU net value, original 421M lifecycle,
  4096 concurrent Cell target host performance, and signed FinalUse all
  remain strict blockers.

## Tests and original execution

```sh
python -m unittest discover -s qualification/stem-optimal-v11 -p 'test_online_route_v11.py' -v
python -O -m unittest discover -s qualification/stem-optimal-v11 -p 'test_online_route_v11.py' -v
```

The read-only workflow runs source tests on every PR. Only exact research
branch pushes reacquire verified original V3/V4/cheap artifact ZIPs, rederive
fit-only threshold, and emit a label-free research receipt. No source-only
success or archived-label replay can grant production authority.
