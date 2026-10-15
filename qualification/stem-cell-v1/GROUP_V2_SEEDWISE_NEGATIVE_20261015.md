# Real Granite97 Group V2: seedwise Split/NDU negative results

**Draft · DENY_ALL · research-only**, additive descendant of [original independent audit #2285](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2285), pinned original summary Git object `e2913669e502238c82c7f8982ead99d7998e99c7`. This extension adds no new pretrained model call, re-training, production selection, native Neuron/NDU effect or main merge.

An original 3-seed, 8-arm Granite97 Group study is source-shared across seed 41/47/53 and uses 96 held tasks per arm/seed, **not three independent future task families**. A different script `group_v2_seedwise_contrast.py` calls the existing strict independently verified aggregate reviewer first, then recomputes the split/static and NDU/static per-seed quality differences and ratios of originally metered **online** CPU. Each original split candidate remains denied by its pre-test selection and the core retains selection.

| Seed | Split − static correct /96 | Split/static online CPU | NDU − static correct /96 | NDU/static online CPU |
| --- | ---: | ---: | ---: | ---: |
| 41 | −3 | 6.80289× | −4 | 2.91706× |
| 47 | +3 | 6.77076× | −1 | 2.87416× |
| 53 | 0 | 6.70597× | 0 | 3.07470× |
| Aggregate | 0/288 | ~6.76× | −5/288 | ~2.95× |

This makes heterogeneity visible rather than hiding a seed-specific success behind a mean. None is a **whole-life equal-cost** or source-independent inference: original Encoder load/feature computation, training and Critic work are not billed into the online CPU columns; full Encoder FLOP count is not known. The original raw 2,666,151-byte model evidence ZIP has not been independently replayed by this child. Source-group metadata SHA and aggregate scores are not external host/publisher signatures.

The new 8-test source-dependent audit checks original three-seed deltas, positive overheads, pre-test split rejections, tampered correctness/cost, missing seed and false promotion. Exact HEAD + synthetic-merge existing workflow runs these tests in standard and optimized Python, preserving original independent 11 tests and existing experiment gate. **Until latest hosted CI actually completes, no current-sha hosted pass is claimed.** A heldout prospective Group family with 64/256/1024/4096 fully paid parent/split and old-task-retention remains required.

`split_winner=false`, `ndu_winner=false`, `natural_future_gain=false`, `production_accepted=false`, `DENY_ALL` — no NDU or Cell Split production activation, model selection, 10T/100T equivalence or main merge.
