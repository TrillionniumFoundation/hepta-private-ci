# Actual learned MemoryCell routing experiment

This directory retains the complete V2 run, including every trained Head and
Router tensor artifact and the per-example invocation ledger. It is a research
mechanism result with `DENY_ALL` authority, not a production activation or a
qualification of a general memory system.

## Result

The learned Router does **not** establish a repeatable accuracy advantage. The
strong pooled single Head has higher mean accuracy in all three holdout windows.
The learned Router has lower mean negative log likelihood (NLL); calibration and
loss differences do not establish overall task superiority. Keep the pooled Head
as the required baseline for subsequent specialization experiments.

Three seeds (7, 17, 29); each entry below is mean accuracy / mean NLL:

| Holdout | Calibration-selected fixed Cell | Pooled single Head | Learned Router |
| --- | --- | --- | --- |
| future_1 | 0.713542/0.729280 | 0.786458/0.857463 | 0.765625/0.674767 |
| future_2 | 0.752604/0.782701 | 0.799479/0.876444 | 0.731771/0.744257 |
| ood | 0.671875/0.816818 | 0.736979/0.907359 | 0.682292/0.816365 |

The individual seed results and paired bootstrap intervals are in
`report.json.gz`. Intervals use 2,000 paired resamples of unique source stories
and are descriptive, without multiple-comparison adjustment. Neither a winner
nor a deployment decision is selected from these holdouts.

## What actually ran

- Pinned EmbeddingGemma2 checkpoint revision
  `914f7f89142e33e77833254d9c9b90c3cef7303b`; checkpoint inventory SHA-256
  `036c9188478057bada1b51ef856f3567509daf1e85efb9da283be1a69be0cb9b`.
- Actual frozen text Encoder: 271,002,624 loaded parameters and 1,084,013,668
  resident tensor bytes. This is the text profile of the 744,371,512 parameter
  full multimodal checkpoint, not a claim that the full model was resident.
- One encoding of 768 historical news examples is shared across all Cells,
  baselines, and seeds. Encoder tensor hashes before and after training match.
- March training: 96 unique stories for Head A, 96 for Head B, 64 separate stories
  for Router supervision. April calibration: 64 Head and 64 Router stories.
  May, June, and publisher-held-out July each contain 128 separate stories.
- Each private gated Head receives 200 actual SGD updates. The Router receives
  200 updates using observed calibrated task NLL from frozen candidate Heads.
  Router training and calibration groups do not overlap any Head learning group.
- The pooled Head receives the union of all 256 March training stories and all
  128 April calibration stories. This stronger control uses the same available
  source information instead of withholding the Router's training data from it.
- Each evaluated arm executes exactly one selected Head per example. The fixed
  arms bypass the Router forward pass. Candidate losses used for Router training
  and all temperature-calibration calls are counted separately from evaluation.
- Actual Head and Router bytes are saved and reloaded with independent retained
  manifest hashes; reload predictions match exactly. The ledger records selected
  and actually invoked Heads, probabilities, costs, and source identities.

**Budget boundary:** inference Head calls are equal; total resident parameter
count, Router overhead, optimizer work, and training compute are not equal.
Observed timings include a shared CPU environment and are not service latency
benchmarks. `plan.json` records these limits before model load and holdout scoring.

## Evidence and reproduction

`inventory.json` records stored and original byte lengths and SHA-256 values for
all 28 original files. JSON files over 64 KiB use deterministic gzip compression;
NPZ artifacts remain their original bytes. For example:

```python
import gzip, json
from pathlib import Path
report = json.loads(gzip.decompress(Path("report.json.gz").read_bytes()))
```

To restore the original artifact layout before calling the existing loaders,
read each inventory entry, decompress entries marked `gzip`, verify the
`original_sha256`, and write the result at `source_path` in a new directory.
The independently retained hashes remain the loader inputs; recomputing a hash
from an unchecked replacement manifest does not authenticate that manifest.

`feature_manifests.json.gz` retains source and FeatureIdentity bindings;
`prediction_ledger.json.gz` retains all predictions; each `seed-*` directory has
Head A, Head B, pooled Head, and Router manifests and NPZ tensors. External model
weights and the source news archive are intentionally fetched by their pinned
identities, rather than duplicated in git.

From the repository root, with the pinned research requirements installed and
operator acceptance of the model/source terms, run:

```sh
OMP_NUM_THREADS=4 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1 \
python qa/stem-bakeoff/real_router_probe.py \
  --candidate embeddinggemma2_740m --snapshot /path/to/pinned-checkpoint \
  --inventory-sha256 036c9188478057bada1b51ef856f3567509daf1e85efb9da283be1a69be0cb9b \
  --cohorts /path/to/news-cohorts-v2 --archive /path/to/news-aggregator.zip \
  --output /path/to/new-run --operator-accepted-terms --threads 4 --batch-size 16
```

The exact code-file hashes used by this run are in `plan.json`. Subsequent
additions to the research directory are not part of this run. The source cohort
manifest and archive hashes are pinned in the same plan.

## Remaining evidence limits

The records date from 2014. These windows are held out relative to the local
training process, not prospective events relative to foundation-model pretraining.
This is four-class news classification, not episodic exact recall, temporal
correction, procedural tool success, personalized memory, or deletion efficacy.
It uses one source family and one Encoder text profile. There is no independent
production evaluator signature, actual cross-node runtime, or multimodal result
in this experiment. A negative or mixed result is retained, not promoted.
