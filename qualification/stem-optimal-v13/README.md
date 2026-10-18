# V13 — original complete pretrained models, same-process **cost-only** pairing

**DRAFT / RESEARCH_ONLY / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL. No main merge, production model selection, FinalUse, Cell Split or external effects.**

Exact parent: [V10 PR #2700](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2700), `4e6ef74380cb158486bb33e447aaddb59c68ad1e`. Original V1–V10 and V12 research evidence remain immutable; V13 is a separate additive cost-only branch.

## Why the previous combined acceptance failed

V10 original hosted run `39073660101` passed CPU source tests and Granite97 original measured matrix but failed Granite47/mmBERT because `trained_head_sha256` did not match historical byte-for-byte. A distinct fully executed V12 [loader/Head diagnostic run `39073620449`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39073620449) confirmed: Granite47/97 had 0 missing/unexpected/mismatched loaded pretrained base keys and identical **initial** Head bytes; nevertheless the separately trained Head parameter bytes did not match, with selected-output differences of ~8.5e-7/3.2e-6. Original mmBERT `AutoModel` had missing `embeddings.tok_embeddings.weight` and 4 unexpected keys; its attempted complete MLM loader failed to materialize a meta tensor. **mmBERT140 therefore remains excluded, not falsely rehabilitated.**

## What V13 actually tests

1. Only Granite47 and Granite97, both original SHA-pinned full safetensors with strict `output_loading_info=True`: any missing, unexpected or mismatched key, any loading error, wrong parameter count or wrong serialized SHA **hard fails** before inference.
2. Pay original 64 FIT Encoder sequences, 100 original Adam Head updates, and *both* full 32-case and selective eight-case runs four times in counterbalanced order in one CPU process with a single resident model and Head. Actually pay 224 Encoder sequence inputs/16 batches per experiment, **not 72**. Real cheap-route cost, pretrained model load, FIT Encoder and Head training are separately metered.
3. Strictly verify original TRAIN/32 HELDOUT cohort, the eight selected case IDs from the sealed original cheap label-free V4 predictions, unchanged original model weight identity and Head **initial** SHA; retain observed old/new trained SHA equality as an explicit boolean. **Do not fake historical byte replay** if it differs.
4. Compare *only the same-run physical selected-versus-full scores* under the unchanged trained Head with tolerance <=5e-4; if this fails, the cost job fails. Historical cross-run score drift is recorded but never used for model-selection admission.
5. Independent label-free **model-free** reviewer reopens the originally archived model/source/cheap ZIPs, verifies actual 224 reported paid sequences, paired order/phase timing/median arithmetic and completeness/denial flags. It cannot independently attest hardware events beyond the worker's self-report.

## Strict scientific limits

Passing this experiment would validate **descriptive same-process CPU cost and within-run result parity only**, not historical learned Head byte parity, prospective task utility, real end-to-end resource savings on target machines, 421M replacement, source-disjoint future windows, 4096-cell production, signed issuer/FinalUse or NDU advantage. The old publisher TEST labels had already been inspected, so there is no new blind quality claim. A selected query timing advantage is not equal to a cold-start lifetime net saving or energy reduction.

Original V12 failure data and old V10 failures remain available, not rewritten. At authoring the V13 exact-hosted work must be checked separately; local Torch fixture tests are not real original pretrained runs.
