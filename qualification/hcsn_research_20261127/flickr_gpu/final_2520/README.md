# Flickr8k GPU panel at 42 minutes per model

The original ai395 run trained 15 captioners across five visual routers and three named seeds. The driver sealed all 15 development-selected weight hashes together and then tested each model in a fresh process. Each completed ten scheduled development observations. The dataset has 5,999 training photos and 1,000 photos in each of validation and test, with five captions per photo. The models share a two-layer width-96 autoregressive attention decoder. Each arm reads all 16 image patches. Compressed arms emit four visual tokens and the dense arm emits 16.

The sealed test includes 64,483 scored caption tokens. Lower NLL and perplexity indicate better prediction. Positive conditioning gain means the matching image had lower NLL than the cyclically permuted image.

| Router | Parameters | Test NLL | Perplexity | Conditioning gain | Mean updates | Mean training tokens |
|---|---:|---:|---:|---:|---:|---:|
| hcsn | 563,540 | 2.908012 | 18.320 | 0.103363 | 195,472 | 80,357,546 |
| smooth | 563,540 | 2.911198 | 18.379 | 0.111252 | 196,008 | 80,578,239 |
| lif | 563,540 | 2.920595 | 18.552 | 0.111587 | 203,589 | 83,694,085 |
| mean | 563,136 | 2.923127 | 18.599 | 0.119228 | 230,742 | 94,854,140 |
| dense | 563,136 | 2.909587 | 18.349 | 0.152489 | 221,788 | 91,173,424 |

## Prespecified quality comparison

The registration requires negative upper 95% bounds for both HCSN-minus-dense and HCSN-minus-smooth test NLL and positive HCSN image conditioning gain. Each contrast uses 5,000 paired image-cluster bootstrap replicates after averaging over the three fixed training seeds.

| Comparator | HCSN minus comparator NLL | Paired image 95% interval |
|---|---:|---|
| dense | -0.001576 | [-0.008021, +0.004932] |
| lif | -0.012583 | [-0.017702, -0.007391] |
| mean | -0.015115 | [-0.021806, -0.008707] |
| smooth | -0.003186 | [-0.006636, +0.000222] |

The registered quality decision is **NOT PASSED**.

## Cost and common quality

Nominal optimization plus model selection totals 630 minutes for the 15 models. Measured optimization totaled 37,783.07 seconds, and checkpoint validation totaled 18.03 seconds. The driver recorded 37,930.84 seconds for the entire protocol subprocess including the final test and statistical summary. Initial acquisition, qualification and the subsequent matched-quality analysis have separate cost boundaries.

The five targets depend on training-token entropy. Entries show the first scheduled development observation meeting each threshold for seeds 17011, 24203 and 39827. Right censoring means every observed NLL exceeded the target. Actual checkpoint times and paired ratios appear in matched_quality.json. The observation grid limits timing precision.

| Validation target | HCSN | Smooth | LIF | Mean | Dense |
|---:|---|---|---|---|---|
| 4.641103 | 20/20/20 | 20/20/20 | 20/20/20 | 20/20/20 | 20/20/20 |
| 4.141103 | 20/20/20 | 20/20/20 | 20/20/20 | 20/20/20 | 20/20/20 |
| 3.641103 | 20/20/20 | 20/20/20 | 20/20/20 | 20/20/20 | 20/20/20 |
| 3.141103 | 120/120/120 | 120/120/120 | 120/120/120 | 120/120/120 | 120/120/120 |
| 2.641103 | censored/censored/censored | censored/censored/censored | censored/censored/censored | censored/censored/censored | censored/censored/censored |

## Replay and provenance

The frozen model and protocol originate at c511a75b04eb24719f9d5e424d190b071c78f261. Earlier GPU receipts are at be42c8242a5986f0acf979cb9773e19633c9a396. The archive preserves per-image loss sums under matching and shifted images, token counts, image hashes, all development histories, the joint seal, runtime identity and timing. The durable ai395 archive retains the selected model weights.

The original seal SHA-256 is 545f0c067deb31d7fc392a690a61e8239f49188d3b287eeb722af38b25ffdd87. The driver recorded completion at 2026-11-27T22:32:16.011421+00:00. The NumPy verifier checks hashes and split separation, checkpoint selection, NLL, conditioning gain, paired intervals and all model-by-target checkpoint crossings.

Concatenate any split archive in archive_parts.json order and compare the complete SHA-256 before running the following command.

```bash
cat flickr42_original.zip.part* > flickr42_original.zip
python verify_heldout.py flickr42_original.zip --output replay.json
```

The sidecar archive contains final_manifest.json, package_telemetry/points.jsonl, package_telemetry/summary.json.

The monitor measured the shared APU package beginning during the 420-second stage. Covered segments exclude gaps, idle correction and facility power. Package readings can include concurrent CPU and GPU work.
