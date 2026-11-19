# P2 original-human MultiRC source owner, without selected Stem

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** This bridge is
stacked on PR #2701, which itself depends on PR #2579. It changes no production
Neuron, model selection, NDU, Artifact CAS, CNS, FinalUse or Cell Split.

## Exact original source and ownership

The upstream P0 original-human MultiRC **material generator** is held at commit
`883b7c107348675153aece3db40a1d00e41c0a09` in this same repository,
`experiments/shared_stem_cell/p0_multirc_semantic_material.py`, exact Git blob
`637a73a8735ff706ac256dca13a0614373255da1`. This is research code in
another Draft branch, **not an independently accepted publication**.

It selects from `aps/super_glue@4e14482c58d790d467ecfb29b6790e1917bf8756`,
original `multirc/train-00000-of-00001.parquet` and
`multirc/validation-00000-of-00001.parquet`. The hosted source owner checks the
full pinned dataset revision, exact LFS SHA-256 of each Parquet and locally
re-hashes all bytes; its Python code is checked out by immutable commit and
verified by original Git blob. No `trust_remote_code`, arbitrary dataset scripts
or model-generated human labels are used.

The original label-independent P0 sampling retains **12 training, 4 calibration,
8 test passage groups**, with both original and no-evidence views per candidate.
The P2 bridge checks the entire source-pair hash and pair inventory. It then
chooses exactly **two original annotated candidate-answer cases per source group**
by *original source case ID only*, never inspecting any human label to select
cases. The resulting 48 rows are 24 FIT / 8 CAL / 16 TEST. Only the actual
original passages are admitted to this first supervised task: the transformed
no-evidence counterfactual carries **no invented human truth label**. The
unselected candidate population is retained as original source material in
the source owner's private workspace, not silently relabeled or scored.

`multirc_source_bridge.py` emits three **label-free** documents: `panel.json`,
`views.json` and a small source identity receipt. Every view retains the complete
original passage, original question, candidate answer, both ordered options,
original case/group/source SHA and exact byte digest; no target or human labels
appear in them. Separate `fit-only.json` includes only authentic FIT human
labels, is written `0600` under a distinct directory, and is NEVER uploaded.
CAL and TEST targets are not exported in any form. The output `token_count`
field is a source-only whitespace-word *estimate*, not a claim of a model's
actual Tokenizer count: both original model implementations must independently
reject any real tokenizer truncation before emitting a genuine feature.

The new hosted research job builds the source directly from exact original
Parquet bytes and reports only the small source summary via GitHub Artifact.
It does NOT upload original source text, per-case feature vectors, FIT/CAL/TEST
human labels or model outputs. It does NOT download/execute 400M/421M weights.
The public source is still not an issuer signature, licensing determination,
pretraining contamination exclusion, future calendar cohort or held-task score.

## Strict dependency before a model claim

1. Observe a terminal successful original-source Parquet and P0 generator CI
   receipt with exact Git source and full publisher byte hashes.
2. Pass this exact 48-case panel/views privately to the existing
   `physical_feature_bank.py`, run BOTH original Laya/Ettin checkpoint forwards
   against **all the same case IDs** without model-specific truncation.
3. Use the preexisting 4,161-param/40-SGD P2 Head with original private FIT
   labels and independent seed/optimizer replay. CAL/TEST labels must be
   accessed only by a separate original-publisher observer after model seals.
4. Qualify independent human-label results, future source families, negative
   transfer, NDU net utility and target-host 64–4096-Cell costs before any
   production candidate is selected or promoted.

The original P1 single unlabelled probe passed true CPU inference on GitHub
Actions #39034514849 for Ettin (447,458,496 tensor elements) and Laya
(421,293,827), but P1 outputs were DIFFERENT decision vs CLS forms. These
original facts do **not** establish accuracy, equal FLOPs, frozen multi-case
features or device readiness.

## Local repeatable source-only tests

```bash
cd qualification/stem-replacement-p0
python -m unittest -q test_multirc_source_bridge
python -O -m unittest -q test_multirc_source_bridge
```

The 18 synthetic fixture tests validate schemas, source group cuts, no-evidence
label prohibition, complete authentic-case pairing, response-option order,
original-question framing, hash/source identities and independent FIT custody.
Passing these synthetic tests does not mean the hosted genuine Parquet source
owner job has run, nor that any 400M/421M pretrained features exist.
