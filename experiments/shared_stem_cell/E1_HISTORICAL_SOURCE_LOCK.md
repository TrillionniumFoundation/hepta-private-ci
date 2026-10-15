# E1 original source-selection lock — empirical integrity increment

**Research shadow only; DENY_ALL.** A publicly sourced parquet filename and hash in a JSON field cannot by itself prove that the actual selected rows and labels remained unchanged. The earlier E1 physical runner and separate pairwise review could accept a different 224-case panel if its input hashes and reports were regenerated consistently. Such post-hoc selection would invalidate a paired comparison.

## Independent original bytes

Completed same-repository GitHub [Actions run 38541658096](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38541658096) succeeded on head `f8d168a7689eb3624d97c44751791badd069e521` and produced research artifact **11886761368**. The actual archive was downloaded, byte-hashed and checked outside the new producer.

- Immutable original ZIP SHA-256: `e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d`.
- Original canonical selected panel SHA-256: `2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4`.
- Pinned raw AG News parquet SHA-256: train `cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5`; calibration/test `3171d3aeee227372165bb0f9e84ebf2bfaf5fc870d034f33a5fc568e7995c672`.
- Original 224 rows: 128 TRAIN (64+64 labels); 32 CAL (16+16); 64 TEST (32+32). Previously observed frozen Laya archive includes **96 uniquely identified CAL/TEST predictions**, and the three original source/experiment hashes agree.

These are **original data-selection and research artifact content identities**. They do not establish publisher origin signatures, producer-independent label truth, nonoverlap with model pretraining, calibrated Reader sufficiency or three *future* windows.

## Real physical E1 gating change

All three existing standalone CLIs — the real pretrained Encoder runner, numerical triplet evaluator, and historical frozen Laya evaluator — now compare the canonical panel SHA against the original fixed digest **before real model execution or numerical scoring**. This is deliberately hard-coded, not a user-supplied `--expected-digest` that could follow a post-hoc swapped cohort.

The main `.github/workflows/hepta-e1-real-public-three.yml` fetches the original successful Actions artifact and executes `e1_source_archive_lock.py` immediately after recreating the hashed public parquet panel and **before downloading any 195–1,500 MB model weights**. It checks the whole archived ZIP SHA, strict source receipt, public comparison identity, every current source text/label/group and 96 archived frozen Laya case identities. On any mismatch the job fails closed and preserves a non-successful model evidence record. The same verified ZIP is reused for later Laya comparison rather than downloaded a second time.

```bash
python experiments/shared_stem_cell/e1_source_archive_lock.py \
  --panel /approved/actual-reconstructed-panel.json \
  --historical-zip /approved/pinned-original-successful-run.zip \
  --output /sealed/e1-source-identity.json
```

A separate no-model workflow `hepta-e1-source-archive-lock.yml` compiles the new audit, runs its adversarial tests and independently checks the original artifact's SHA and preserved Laya CAL/TEST row inventory without any new weights.

### Negative coverage and exact-source testing

**23/23 focused tests** passed locally on the exact GitHub blob SHA pair:

- `e1_source_archive_lock.py`: `27d06785f66bcc8de4dc2f1e31974eb50ac4b720`;
- `test_e1_source_archive_lock.py`: `44e7f835313d86a79c9cb8f3fd9d8362c348b7bd`.

The synthetic tests include changed original labels, text, class mapping, case identifiers, source groups and duplicates; missing or swapped historical Laya predictions; invalid/duplicated ZIP entries, unsafe path traversal and nonfinite/duplicate JSON. Three separate command-line fault tests check that **all three real/score entry points reject changed sample selection**, including the pretrained runner *before model loading*. Those three CLI tests were locally executed against compatible local research source copies patched with the same source-lock rule; the current GitHub exact-head hosted workflows must still establish integrated success.

**Important limitations:** Local tests and the archived real Gemma/Laya run do not show newly executed Granite/mmBERT pretrained weights. E1 true future datasets, E2 independent learning utility, E3 Granite/DINOv2 vs native Gemma, E4 actual audio/video, E5 target native Worker/WAL, signed NDU and `blocking-ci` are still unqualified. Neither this evidence file nor a green unit test may promote a production Stem.
