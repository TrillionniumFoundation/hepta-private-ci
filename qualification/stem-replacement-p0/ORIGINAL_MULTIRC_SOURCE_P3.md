# P3 original-human MultiRC source-owned P2 panel adapter

**Stacked DRAFT / DENY_ALL / HOLD_NO_GO** on P2 PR #2701 (itself stacked on
P1 PR #2579). This source-owner adapter has no pretrained weight access, model
loader, learning optimizer, publisher permission, production authority or
Cell Split permission. The source-only unit tests are **not** original
MultiRC/421M/447M model efficacy tests.

## Original published identity

The source record is the already built **P0 original-human**
`hepta.p0.multirc-human-semantic.v1` source-owner output from
`experiments/shared_stem_cell/p0_multirc_semantic_material.py`, reviewed at
PR #2419's original code ref `883b7c107348675153aece3db40a1d00e41c0a09`.
Original public dataset source is
`aps/super_glue@4e14482c58d790d467ecfb29b6790e1917bf8756`, paths
`multirc/train-00000-of-00001.parquet` and
`multirc/validation-00000-of-00001.parquet`, with *actual* full original-file
SHA256 recorded in the P0 source owner output. It selects 12 training, 4
calibration, 8 test source passages, with both original and no-evidence views
for each candidate. It is a tiny observational cohort, **not** the official
SuperGLUE leaderboard score. Independent original-source byte/label/usage
qualification is not implied by having a consistent derived JSON artifact.

## Authoritative-data division

`original_multirc_p2.py` consumes ONLY upstream source-owner P0 `fit.json` and
`blind.json`. It checks exact source repo/revision/protocol, original source SHA
fields, complete immutable original `panel_id`, paired original/no-evidence
candidate identity, all question text and SHA, source groups and human labels
from the supplied fit owner. A regenerated original P0 source-owner receipt
requires the genuine original parquet bytes and its independent source
validator; this bridge does **not** download data or independently authenticate
the original dataset issuer.

It chooses exactly four **ORIGINAL** human-label candidate-answer cases per
passage, sorted **by source question/answer/case ID, not correctness**. All 24
distinct source groups yield 96 cases (48 FIT, 16 CAL, 32 TEST). For a common
binary question, each native original evidence/question/candidate-answer view
uses ordered `not_supported`, `supported` alternatives. No `no_evidence`
example is trained or given a new fabricated human label.

Three separate **source-owner-only** files are created, with create-once 0600
permissions:

- `panel.json`: SHA-bound original source IDs, fit/cal/test groups and 4,161-
  parameter, 40-step Head budget, but **no original text or target label**.
- `original_views.json`: the 96 original model-facing exact evidence/question/
  option strings, but **no FIT, CAL or TEST target labels**. It is the only
  source-owner text manifest the subsequent frozen Encoder bank producer reads.
- `fit_owner_only.json`: **FIT original human labels only**. It stays outside
  the frozen feature producer; later Head training can be separately granted
  FIT-only access. The original TEST human gold remains with the independent P0
  scorer/source owner and is *never* read by this adapter.

`token_count` in `panel.json` is a *label-blind lexical source budget estimate*,
**not** the model tokenizer length. The original physical bank must separately
record every actual native tokenizer count and reject any silent truncation.
One source passage generates multiple candidate questions, so all its samples
retain exactly one group and one split. Eight held passages are too few for an
independent statistical superiority claim. Prior pretrained contamination,
license qualification and longitudinal future windows remain explicitly unverified.

## Run (after separate P0 source owner qualification)

```bash
python original_multirc_p2.py --fit /secure/P0/fit.json \
  --blind /secure/P0/blind.json --out /secure/P3/original-selected

# Exactly one original model per isolated read-only physical job:
python physical_feature_bank.py --model ettin400 \
  --panel /secure/P3/original-selected/panel.json \
  --views /secure/P3/original-selected/original_views.json \
  --receipt /secure/P1/ettin-original-receipt.json \
  --stage /secure/P1/ettin-original-verified \
  --bank /secure/P3/ettin-original-private-bank.json \
  --report /secure/P3/ettin-source-forward-cost.json
```

Repeat for Laya421 using its *distinct* pinned source receipt/byte-checked
checkpoint, then perform P2 matched 4,161-param/40-step Head training. All
real source, model, Head and held-label evidence must be independently reviewed
before any accuracy, negative-transfer or resource utility claim.

The P3 source-only unit tests use **synthetic, invented** 24-passage JSON with
the same *structural schema* only. The code is not evidence that the real P0
publisher cohort has been materialized, downloaded, licensed or scored.
**No model winner, production model selection, NDU/CNS final-use or Cell Split.**
