# Frozen captioner substitution on 256 development photos

The three trained scalar-router HCSN checkpoints all accepted the single-, double- and four-path lookup transformations. Native and n=1 logits agreed exactly on the compatibility test for each model. The chosen 256 official Flickr8k validation images are disjoint from the 128 prior scheduled selection images. They contributed 1,280 captions and 16,412 scored tokens. All reported scores concern the same stored states. The entire substitution used a single CPU thread and zero optimizer updates.

| Number of independent microdomains | Token NLL | Minus n=1 | 95% paired image interval | Image-conditioning gain |
|---:|---:|---:|---|---:|
| 1 | 2.94267894 | 0 | [0, 0] | 0.08182942 |
| 2 | 2.94273065 | +0.00005170 | [−0.00028282, +0.00039185] | 0.08214000 |
| 4 | 2.94286190 | +0.00018296 | [−0.00048448, +0.00089389] | 0.08235022 |

The intervals resample 256 photos after averaging over the three fixed weight sets. The paired loss estimates resolve no advantage for either substitution. Their small magnitude supports functional compatibility in this small developmental experiment. The full previous model had used the Flickr8k validation corpus. This exercise neither retrained the alternative dynamics nor accessed the official test and independent COCO cohorts. It provides no time-to-quality measurement.

`frozen_results.json` gives seed-wise NLL and conditioning, the exact selected-state SHA-256 hashes, array receipt and runtime information. `per_image.npz` contains loss sums, token counts and image digests. Run `python replay_frozen_scores.py` in this directory to reproduce all nine model summaries and the paired intervals. `FROZEN_DIAGNOSTIC.md` and its implementation were registered at b595864204936817a7b5c8ffe6fb4ceeaacb78df before the independent CPU process began.
