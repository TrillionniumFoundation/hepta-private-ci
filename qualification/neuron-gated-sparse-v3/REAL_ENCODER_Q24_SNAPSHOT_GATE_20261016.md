# Frozen real-Encoder → Q24 32D Feature Snapshot admission contract

**DRAFT / DENY_ALL / not an Encoder feature producer.**

The source of truth is two distinct frozen hosted lineages: public ModernBERT +
BANKING77 study #1825, and independent synthetic private Q24 Cell study #2426.
They do **not** share a genuine 32D Q24 feature snapshot. No valid scientific
comparison of their task quality is currently possible.

`real_encoder_q24_snapshot_gate.py` is a strict *consumer* for when the actual
pretrained Encoder owner emits a physical feature snapshot. It demands a
separately frozen source registry file, exact external registry SHA, frozen
Encoder weight/model SHA, and an external projection/model SHA. Projection-fit
case IDs must equal **only** the originally registered fit IDs. Every registered
heldout ID must have exactly one 32-element signed Q24 vector; train and
heldout IDs must be disjoint and cover the entire snapshot. Stored feature
rows cannot include any label fields. Non-integer, out-of-bounds, NaN,
unexpected fields, duplicate JSON keys and symlink sources fail closed.

CLI example (external identities are supplied by an independent owner):

```sh
python qualification/neuron-gated-sparse-v3/real_encoder_q24_snapshot_gate.py \
  --registry /path/to/independently-frozen-case-registry.json \
  --registry-sha256 FROZEN_EXTERNAL_SHA256 \
  --encoder-sha256 FROZEN_MODEL_SHA256 \
  --projection-sha256 FROZEN_TRAIN_ONLY_PROJECTION_SHA256 \
  --snapshot /path/to/real-encoder-q24-32d-snapshot.json \
  --output /new/create-once/research-preflight.json
```

**Important scientific and security limitations:** A caller can author both
snapshot and its self-declared Encoder/projection hashes. Even after the schema
passes, independent real pretrained model invocation, signed source ownership,
feature projection fitted exclusively on train cases, physically stored
weights, dataset/source licenses, target host, training compute, true Q24
timing, frozen deployed no-change V1, evaluator independence, prospective
future-window effects and NDU are NOT authenticated by this consumer.
The output unconditionally denies promotion and final-use. The next owner
must implement the *producer* with actual loaded public Encoder weights,
immutable case ID/source-text binding and a projection whose frozen trained
artifact is independently attested, before feeding real Q24 candidate training.

Local synthetic protocol unit tests are neither trained models nor real
public Encoder execution. No merge into main, live route changes or Cell
physical split.
