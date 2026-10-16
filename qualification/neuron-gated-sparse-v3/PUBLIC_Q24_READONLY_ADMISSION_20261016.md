# Read-only admission for actual public ModernBERT 32D Q24 snapshots

**Research-only / DENY_ALL** child of [PR #2462](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2462)
at `cc497f3ea01aff43bde75aa8b50a8aec9f01cd88`. It never modifies a
selected production Cell, temporal Q24 kernel, registered model, NDU,
CAS/signature authority, CNS route or final-use. It does not train a Head.

## Why this distinct reader matters

The real pretrained-Encoder feature producer lives on an independent source
lineage: [PR #2472](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2472).
It physically executes pinned complete ModernBERT, runs the same BANKING77
64-fit/32-official-test inputs and fits 768→32 PCA **using only training data**.
The Q24 module's previous inputs were explicitly synthetic. Cross-lineage
training is forbidden until exact source identity and independent feature
replay both pass.

## Standalone read-only public source admission

`public_q24_independent_cases.py` consumes only `SEALED.json`, the source
case registry, pooled F32 feature safetensors, the train-only PCA32 safetensors
and the saved 32D signed-I64 Q24 feature tensors. It requires:

- registered pinned model `answerdotai/ModernBERT-base` revision
  `8949b909ec900327062f0ebf497f51aef5e6f0c8`;
- BANKING77 source revision
  `57ec275d8078af65b7731c2a98be812d844a6d6b`;
- 64 authentic training-case IDs/labels and 32 official test-case IDs,
  with **no heldout labels or extra test fields**;
- physical file SHA256 and byte lengths, tensor shapes/dtypes, actual
  training-only PCA reconstruction and exact Q24 per-coordinate replay;
- no invented original production A0 owner, true future window, signer,
  independent pretrained source certificate or model deployment authority.

It then writes a create-once **reader-neutral** four-class public Q24 data
envelope. Its rows contain `case_id` and 32 I64 feature values; **training**
rows additionally carry the original four-class target. Heldout rows carry
no label. This is *not* a temporal tick/sequence trace and cannot be
misrepresented as one: BANKING77 utterances do not have observed state
transitions or a genuine future time index.

The input is **not** accepted by the existing timestamped binary
`matched_train.py` parser. Future work must add a separate, strictly
bounded *independent-case* native Q24 training/evaluation owner with four
one-vs-rest classification Heads, original no-change V1 freeze and
independent later observer labels; do not silently attach artificial clocks
or claim longitudinal negative transfer.

## CLI

```sh
python qualification/neuron-gated-sparse-v3/public_q24_independent_cases.py \
  --snapshot /path/to/actual-PR2472-sealed-snapshot/ \
  --output /new/output/public-q24-independent-cases.json
```

`--synthetic-fixture-only` exists **only for unit regressions** and will
never allow a fixture to claim the actual pinned pretrained source.

The new `test_public_q24_independent_cases.py` runs real Torch tensor
serialization under a synthetic unit fixture, including corrupted Q24,
changed PCA with forged hashes, leaked heldout labels, duplicate JSON, and
unauthorized production-source claims. Both normal and `python -O` are
required in the existing pinned physical CI; the ordinary A0 owner remains
Torch-free and skips heavy physical tests.

**Nothing in this reader alone establishes accuracy, future task utility,
equal training FLOPs, 4096-Cell target-host resource use, or production
acceptance. No model promotion / no main merge / no CNS cutover.**
