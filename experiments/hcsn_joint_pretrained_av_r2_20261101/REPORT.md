# Separate frozen Anew + Vpretrained + R1T: joint gate fails

The separate candidate reaches **81.7130% AVT relation accuracy versus 80.0926% clean AT**, a **+1.62037 percentage-point** difference. The six-actor 95% paired interval is **[-2.31481, +4.86111] percentage points**, crossing zero. Audio is **69/72 (95.8333%)** and video **39/72 (54.1667%)**. The predeclared joint gate requires both frontends above 90% and a strictly positive accuracy-interval lower bound; **it fails both the video and paired-increment conditions**. All provider and relation candidates remain frozen.

| Frozen relation head | Accuracy | Brier |
| --- | ---: | ---: |
| Clean AT, [pA, pT, pA×pT] | 80.0926% | 0.1423606735 |
| AVT, seven polynomial products | 81.7130% | 0.1422041704 |
| AVT minus AT | +1.62037 percentage points | -0.0001565031 |

The actor-block Brier-difference 95% interval is [-0.0374884674, +0.0430918246]. One hundred frozen-head within-actor video shuffles have mean **78.21991%** and range **[74.07407%, 81.48148%]** relation accuracy. These are descriptive negative controls with no refitting or selection; the registered paired gate remains false. All 100 values and the six actor differences are retained in `results/run001/RESULT.json`.

## Candidate and attribution

Both providers' exact 288 train clips, binary DFA/IOM targets and common four 18-fit/6-held actor partitions were checked before relation fitting. Audio/video OOF probabilities map to their own episode slots; the original nested R1 text probabilities remain bit-identical. The 1152 training relation labels independently check all-three-sentences equality. Only two fixed C=1 heads were fitted, each with its own train-only normalization; provider neural weights, descriptors and full heads were not fitted again. Clean AT scores are bit-identical to the separate new-audio clean AT comparison.

Source/protocol publication: `5fb3d6cf116dff2db76d0dbe2ca4a94a2b7d0fe5`. All-head publication: `c7ead309b20d96367aaca9332bee79f68ed3ccef`. Both preceded original development extraction. `SOURCE_FREEZE.json` and `CANDIDATE_FREEZE.json` bind exact providers, OOF arrays, heads and training records; none changed after development. `INDEPENDENT_REVIEW_REFERENCES.json` binds independent fixed-head, mapping, cross-lane and bootstrap/shuffle recomputation.

This separate provider combination preserves the primary pretrained-V comparison using fixed R1A/T. It is an ordinary probability-head frontend study, not a test of analytical-core contribution. The original six validation actors are historically exposed development, not independent population confirmation. The video's offline presentation prefix has unqualified compressed-frame reference lookahead, and neither provider establishes live causal packet availability. Production activation, GPU/energy results and all-blockers-closed remain false or unmeasured.

## Incremental cost and reproduction

Two outer receipts sum to **6.341840 CPU seconds**: 3.281714 for the two relation fits with startup and 3.060126 for final fixed-head evaluation/bootstrap/shuffles. Their summed wall is 7.215230 seconds. Provider acquisition, extraction, fitting and inherited pretraining are separate costs; they are referenced, not added again to this incremental sum. The audio component alone records 161.391499 measured CPU seconds. Source preparation, review, finalization and neural pretraining are unmetered, so no complete lifecycle or steady inference cost is asserted.

Use cached provider validation features and the command in `README.md`; no upstream checkpoint is needed for this scoring stage. Retain original predictions and candidate locks. `results/run001/VALIDATION_OUTPUTS.npz` saves both providers' per-clip outputs plus all 288 relation probabilities, predictions, labels, actors and weights. `ARTIFACT_MANIFEST.json` binds the retained component artifacts.
