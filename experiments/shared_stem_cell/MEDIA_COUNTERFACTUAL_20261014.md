# Real multimodal counterfactual admission (research-only)

P3 adds a **post-seal** scored pairing contract for the EXISTING
\`media_execution.py\` and real public image/text and optional audio/video
material. A valid paired record keeps the SAME prompt, Encoder/preprocessor,
scope and Head revision, but changes exact source-bound media bytes. An
independent review manifest must provide BOTH original and counterfactual
truths that differ. No reviewer truth is synthesized from a rotated media
feature, a CLIP embedding, a model prediction, or a source file name.

The \`media_counterfactual.evaluate\` oracle reports both-correct,
original-correct, changed-correct, and failure to change prediction when the
independently supplied truth changes, grouped by modality/contrast/holdout
split and real source family. Video temporal reordering requires the SAME
frame digests in a different order and monotone real timestamps. Missing
actual physical work remains null. Unpaired or drifted artifacts fail.
This is stricter than masking or cyclically rotating unlabeled image tensors,
which cannot themselves prove semantic counterfactual necessity.

This module neither downloads nor invents natural media, sources/independent
reviewers, model weights, energy counters or true future windows.
Exact SHA binding is necessary but does not authenticate a claimed observer.
Thus all generated receipts explicitly deny independence certification,
cross-modal generalization and production acceptance.

Run \`python -m unittest -v experiments.shared_stem_cell.test_media_counterfactual\`.
