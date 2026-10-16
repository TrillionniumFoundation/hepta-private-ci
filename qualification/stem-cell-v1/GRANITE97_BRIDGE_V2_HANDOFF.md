# V2 physical Granite97 → multimodal Cell feature bridge

**Status:** DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.

## Exact bases and tested source

- Integration base: \`main@f8c9419df6ddeb36ff8b522a50219981fb8d9345\`.
- Existing genuine pretrained research producer/reviewer source: PR #2427, frozen \`d2cb3e66172157172a78a2aa35dadfc6508497b9\`, original four Git blobs SHA-pinned in the workflow.
- Actual upstream model identity: \`ibm-granite/granite-embedding-97m-multilingual-r2@835ad14087e140460703cf0fae09f97d469d65c2\`.
- Previously separately audited original model-material content baseline: \`9d39552804582ee18cd61992e012510feae4cddb492b3b74808f6f46f494b0d8\`; this is not a publisher's cryptographic signature.
- Original text fixture is 347 bytes and explicitly *constructed*, not a real task, a source-disjoint test or a withheld-label evaluation.

## What the new V2 code actually enforces

\`granite97_feature_bridge_v2.py\` accepts complete original source bytes, original frozen producer \`export.json\` and independent separate-process \`review.json\`. It checks exact closed field sets, duplicate-free JSON, original model/revision/material identity, source SHA, token ID ordering, attention masks, complete token digest, Q24 signed big-endian width and every numeric value, complete export-byte SHA and reviewer Q24 digest, model replay marker, declared forward CPU/wall counters, principal/purpose, epoch/generation and unexpired research data session.

The V1 384D source-bound FeatureEnvelope is then built *only from reconciled input bytes and numeric features*. The V2 preprocessor key binds normalizer + preprocessing + complete token input digest together, so distinct token sequences do not silently share a cache identity. The bridge does not accept an isolated \`reviewed=True\` assertion, an unpaired producer result, a different real checkpoint, or an identity-adapter record presented as rational8-v1.

Local original-source code is exercised by \`test_granite97_feature_bridge_v2.py\` (seven unittest methods with multiple adversarial mutations) under Python and \`python -O\`; this does not execute a pretrained model. The byte-bound method itself can run in CI without Torch/network.

## Physical experiment and exact distinction of evidence

A new read-only GitHub Actions workflow executes the same original, SHA-checked V9 producer and independently implemented reviewer in **separate Python processes**, using the exact immutable public checkpoint. Only after a matching second actual numerical replay does it invoke the new bridge CLI, emitting a sanitized JSON with source/model/input/feature/review digests and observed source-side costs. The workflow is **not complete until the original physical steps actually succeed on its exact new SHA**. A queued, cancelled, skipped or failing job never constitutes physical evidence.

The physical Job's separate producer and reviewer processes run on the same hosted runner; they are independent software processes, *not* physically isolated owners or hardware attestations. The model is loaded by those original processes, **not** by the new bridge; the bridge truthfully declares \`bridge_observed_forward_count=0\`. Individual costs are self-reported from the actual producer/reviewer programs and not a full lifecycle, GPU/energy or target-host benchmark. The constructed input is not new semantic efficacy evidence.

## Open qualification blockers

1. No independent signed source/model issuer or authentic per-workload host attestation. Never promote to ModelWorker selected authority/FinalUse.
2. No real target data or trained Cell Head; no demonstrated increase in Reader accuracy or Cell learning capacity.
3. No verified image, audio or video source-bound *physical* encoder chain yet. V1 permits those envelopes but cannot prove they are actual pretrained outputs.
4. No repeated model encoding across 64/256/1024/4096 Cells with source-scope-equivalent matched 421M controls and measured end-to-end p99/RSS/recovery.
5. No prospective source-independent human/label-adjudicated multimodal necessity, no independently adjudicated old-task retention or future-window Cell Split gain.
6. No automatic merge, split, CNS/Control/CAS/learning.artifacts mutation or production privilege. Existing \`blocking-ci\` remains mandatory.

## Reproduce source-only boundary

\`\`\`bash
cd qualification/stem-cell-v1
python -m unittest -v test_multimodal_stem_v1 test_granite97_feature_bridge_v2
python -O -m unittest -v test_multimodal_stem_v1 test_granite97_feature_bridge_v2
\`\`\`

Run the exact SHA-pinned physical job only on the research branch. An unsigned source/feature proof may be inspected as scientific data, never treated as authority or successful human task evaluation.
