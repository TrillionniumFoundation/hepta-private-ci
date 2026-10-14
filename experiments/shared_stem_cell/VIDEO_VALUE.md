# Disjoint-source learned continuation value for shared video Cells

**Research only.** This is one *linear conditional expected correctness gain*
example, not a general Neural Differential Utility / FBSDE implementation,
learned reasoning ability, or permission to promote a Cell.

The existing public MP4 staging, frozen CLIP, source-video identity, original
OrderBlind/EndpointDelta/TemporalGRU study and the anytime confidence study
remain intact. This independent pilot tests whether a *learned continuation
value* should replace the cheap confidence threshold when asking a shared CLIP
tower for the next two frames. The purpose is comparison, not presumed gain.

## Explicit disjoint-source roles

The ten frozen source videos are partitioned before task labels affect decisions:

| Source cohort | Registered videos | Paired 8-frame rows | What can use their labels |
|---|---:|---:|---|
| Reader training | 4 | 32 | Train one 24-state four-exit GRU, 80 updates |
| Value-critic fitting | 2 | 16 | Ridge-fit next-pair correctness changes, **after** Reader freezes |
| Calibration | 2 | 16 | Choose fixed, confidence or value policy; no weight refit |
| Holdout | 2 | 16 | Score only after policy and all predictions sealed |

The six registered original train sources are split by their fixed cohort order,
first four for Reader and last two for critic. This reduces the Reader's training
examples relative to the 48-row original anytime study: results across the two
studies must **not** be interpreted as a controlled critic-only ablation.
All six arms **within** this study use precisely one frozen Reader.

For each critic record and depth 2,4,6, the fitting target is
`I[next_depth_correct] - I[current_depth_correct]`, in {-1,0,+1}; the known
label is available only to fit the critic, not when making an online decision.
Five observable features — intercept, current top probability, class margin,
current entropy, normalized depth — feed one fixed-ridge linear regression per
depth (ridge=0.5). Fifteen scalar coefficients total, with measured fit cost.
No future frame features, future labels, source IDs, or hidden answer are input
to the online critic. The one-step expectation can miss multistep gains and
is not an optimal dynamic program.

## Calibration and actual streaming

At depths 2/4/6/8, compare all fixed-depth baselines, the existing confidence
grid `[0,.55,.65,.75,.85,.95,1.01]`, and value prices
`[0,.005,.02,.05,.1,.2]` (accuracy units per pair). A confidence/value
policy is eligible only if its **calibration correct count** reaches the best
fixed-depth correct count; otherwise that family actually falls back to the
best fixed-depth control. Among eligible rules choose fewest exact SHA-unique
CLIP frame features, then physical CLIP calls, requested frame rows, and
correct count. Equal-resource ties prefer fixed control. These are empirical
calibration checks on only two sources, not independent quality guarantees.

Every holdout arm runs with its **own** `FrameCacheTowers` while sharing the same
frozen Reader and physical CLIP model. Each arm requests 2-frame chunks and
checks returned feature shape, values, and exact timestamps. The value family
physically stops when the learned next-pair gain is no greater than its selected
price; no later CLIP frame calls are made for that row. The original confidence
family and fixed 2/4/6/8 controls run separately and must **all** be charged:
the whole research experiment is more expensive than the one selected path.

Reports include full source/model and selection identities, per-frame stop
traces, paired reversal accuracy, full-row accuracy/NLL, loaded model parameter
count, critic parameter and fitting cost, requested frames, unique features,
cache hits, physical CLIP calls, model loading, per-arm wall intervals, and descriptive nearest-rank
p50/p95/p99 per-row intervals (16 correlated rows, not population tails), plus
per-source-video correct counts.
Energy, total FLOPs, peak process RSS and independent population validity are
null or explicitly unverified. The video stage still fetches, decodes, stores,
and verifies all registered frames, even those the later Reader never encodes.
No original MP4 or derived PNG is permitted in retained workflow artifacts;
the source repository's license status is not positively established.

## Reproduce after the existing public-video stage

```bash
python -m experiments.shared_stem_cell.video_value \
  --manifest /staged/video-study/manifest.json \
  --output /staged/video-study/value
python -m experiments.shared_stem_cell.audit_video_value \
  --root /staged/video-study
```

The independent *standard-library* auditor recomputes the fixed linear ridge
coefficients (Gauss–Jordan, not the runtime torch solver), predeclared calibration
grid, actual stop decisions, cohort coverage, heldout correctness and exact
cached-frame cost arithmetic. Its verdict attests **archived consistency only**.
It cannot independently attest native CLIP forward calls, source licensing,
true population independence or correct model weights. Corrupted or internally
inconsistent receipts fail closed. All candidate outputs remain research-only;
no CURRENT, FinalUse, model selection authority, or effect boundary changes.

## Cache-aware marginal work ablation (2026-10-14)

The legacy `value` policy charges one fixed accuracy-equivalent price for
*every* requested next-frame pair. That price is not the true marginal frozen
CLIP cost when previous forward/reverse requests have populated the SHA cache.
The new `cache_value` arm uses **the same frozen four-exit Reader, same 15
critic coefficients, same source-disjoint critic/calibration split, and same
predeclared price grid**. It adds **zero trained parameters**.

At depths 2/4/6, the decision may inspect only the **identities** of the next
pair to count how many additional physical CLIP calls would be required
(0 if both frame SHA identities already cached, otherwise 1). It cannot access
future pixels, future features, future Reader state or labels. Continue when

```
expected[next-pair correctness change | current Reader output]
    > 0.005 + grid_price * marginal_physical_CLIP_calls
```

The `0.005` is a predeclared accuracy-equivalent proxy for the two GRU state
updates and metadata operations even on a full cache hit; it is **not**
measured wall time, FLOPs, power or a calibrated machine utility. Cached
CLIP computation may be avoided, but Reader arithmetic is not free. Only the
actual `FrameCacheTowers` invocation counts show physical calls saved.

The calibration selection uses an exact replay of the same FIFO case order,
SHA membership updates and 2-frame chunking as the holdout runtime. The new
candidate must attain the *best fixed-depth calibration correct count*;
otherwise it falls back to the best fixed-depth policy. Previously existing
`value`, `confidence`, fixed2/4/6/8 and all historical experiments remain
unchanged and execute as separate charged arms, so whole-study cost rises.
The new independent-stdlib archive auditor reconstructs the critic, both
policy grids, cache membership **at each candidate stop**, physical-call
marginal, actual per-pair forward counts and the final label-blind policy.

Synthetic regression demonstrates the new arm can continue with no **new CLIP
call** on a cache hit while the old fixed-price arm stops, with unchanged
Encoder count but two additional GRU frame updates. This is only a mechanism
counterexample, not improved pretrained-CLIP accuracy. The source corpus has
only two held-out videos and is not an independent future population; the
actual real-CLIP result, full end-to-end performance and hardware accounting
remain open. Production promotion, FinalUse and general NDU/FBSDE remain off.
