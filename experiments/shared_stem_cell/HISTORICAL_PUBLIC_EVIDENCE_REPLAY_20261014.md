# Observed public Stem and multimodal results: source-bound historical replay

**This is a re-audit of an already completed public development run, NOT a new
model generation, new reader, independent certification, production promotion,
or evidence that the new P1/P2/P3 tests already passed.**

Source: PR #1699 exact source `2a9f3c0de3960048549e3168da42f8d736aff49a`,
[GitHub Actions run 38511456555](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38511456555).

Verified original artifacts downloaded from GitHub Actions:

- Public pretrained: artifact `11870475540`, outer ZIP SHA256
  `195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7`.
  Original consolidation predictions SHA256
  `51114975c1cd6e4e58caf45bd60279f697b5f1259f436930c0a2367136bdc19b`
  matches the original producer report. Actual stored AG News dataset SHA matches
  the producer manifest; all 32 held-out case identities, source groups, scopes,
  source input digests and original 4-class labels were rechecked.
- Public media: artifact `11870026534`, outer ZIP SHA256
  `79a2ac20ecebbb41c7584d9dbda7f1b2efefdf04a7f32c0c61d00f733a903de9`.
  Both original 32-case and separate 64-case ScienceQA/CLIP prediction byte
  digests match their published reports. These are not independent/future
  natural truth-flip cohorts.

## Real mmBERT-small / AG News development observations

Model: `jhu-clsp/mmBERT-small`, frozen publisher model revision
`abc32620dd4f6ab06f5fbe905dc25f310618e09f`.
Dataset: `fancyzhx/ag_news`, 64 training + 32 calibration + 32 held-out rows.
Independent source-family independence is **NOT verified**; each recorded group
is a distinct record identity.

| Actual Head | Heldout correct |
| --- | ---: |
| gated | 22/32 |
| low_rank | 21/32 |
| linear | 18/32 |
| sparse_expert | 13/32 |

Same-producer split controls: unchanged parent 26/32; continued parent 25/32;
inherited split 21/32; inherited unsplit 25/32. No split superiority.

Same-producer System2 controls: no recurrence 25/32 with 32 state transitions;
adaptive linear NDU 25/32 with 32 transitions; fixed recurrence 24/32 with
128 transitions; ordinary adaptive recurrence 24/32 with 50 transitions.
No demonstrated incremental NDU/FBSDE reasoning gain.

Actual shared encoding: 128 inputs in 16 batched physical forwards.
When 8 inputs were repeated four times (32 requests), cache batching required
one physical Encoder forward and 24 feature reuses, compared with 4 batched
no-cache forwards and 32 singleton forwards. Observed hot-path wall:
488,463,216 ns cache, 1,955,408,458 ns batched no-cache and
1,976,135,202 ns singleton. Very small controlled correlated cohort;
NOT end-to-end or 1024/4096-Cell speedup. Actual FLOPs/peak RSS/energy are null.

## Recomputed P2 paired consolidation failures

Teacher bank 22/32, 12,384 Head parameters. Hash-reopened original
`hepta-consolidation/predictions.json` checked against all 32 exact source
labels; correct-count arithmetic matches the stored producer report:

| Candidate | Heldout | Improved cases vs bank | Lost cases vs bank |
| --- | ---: | ---: | ---: |
| bank / unchanged | 22/32 | 0 | 0 |
| supervised shared | 23/32 | 4 | **3** |
| KL distilled | 22/32 | 4 | **4** |
| residual_corrected | 20/32 | 0 | **2** |
| ridge_residual_corrected | 21/32 | 0 | **1** |
| ridge_selected | 21/32 | 0 | **1** |

The original overall calibration-selected consolidation remained `bank`.
The ridge sub-profile selected `residual_corrected` at calibration, but had
one historical held-out regression. The new source-family guard in this PR
would expose these losses; the original generator did not run the new guard.
The new candidate is NOT retroactively credited with producing these labels.

## Real ScienceQA/CLIP and text-only Reader observations

First eligible holdout 32 cases: image 9/32, image+text 8/32, text 8/32.
Same-model image+text probe: full 8/32, mask image 3/32, mask text 12/32.
Separate 64-case eligible cohort: image+text 20/64, text 21/64,
calibration-selected image+text 22/64. On its same-model image+text probe:
full 20/64, mask image 22/64, mask text 10/64.
Both cohorts used real publisher-bound CLIP model weights; Qwen reference
performed 16 **text-only** attempts on each cohort and yielded 6/16 exact
letter outputs in each, **not** multimodal generation.

These observations show neither positive multimodal generalization nor
a verified semantic counterfactual truth flip. Masking or rotating one
frozen feature is not equivalent to an independently adjudicated new
natural-image correct answer. Audio/video natural tasks and energy metrics
remain unverified.

## Research claim and release boundary

All numbers above are historical diagnostics from one already exposed public
producer run. No new model inference/training was carried out by this replay.
No independent observer/semantic adjudication, 421M copied-model physical
baseline, matched total FLOPs, future-window retention, signature, final
recovery, artifact promotion, or production FinalUse is established.
The exact-head new research workflows and repo-wide blocking-ci must pass
separately. Do not count repeated cases/seeds as independent samples.

Standalone replay JSON artifacts (downloadable in original analysis):
`hepta-public-stem-replayed-observations-20261014.json` SHA256
`8689679ca4f68bad08781f9da6fd1c0c68fb0f27895ca0b0807e31fecca6b39b`;
`hepta-public-multimodal-replayed-observations-20261014.json` SHA256
`bd7528263048eaeaa43ddf37b37b4cc1cc0c3f60f779340be31f741a7ff2f470`.
The source code for producing these independent diagnostic JSON summaries
was run outside the PR; they are provenance-bound human review evidence,
not an in-repo new acceptance signer or selection receipt.
