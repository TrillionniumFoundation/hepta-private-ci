# Natural scanned-document extension, 2026-10-26

This is a completed, bounded image-and-text information-extraction experiment on
real scanned receipts. It produces structured UTF-8 answers and a corresponding
annotated receipt PNG. It uses a frozen OCR engine and explicit extraction rules;
it does not establish general complex image-text reasoning, train a multimodal
large model, or integrate the original Hepta neuron.

The fitted continuation gate selected the cheapest fixed policy. It gave the
same answers as fixed base OCR. More expensive OCR did not improve aggregate
field exact match. These negative results are retained without test-set tuning.

## Frozen data and allocation

The source is [jsdnrs/ICDAR2019-SROIE](https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE),
revision `bffe40c26759f3376ec2b3ae9031dbba54cd587c`. The downloaded dataset card
declares CC-BY-4.0 and credits the original ICDAR2019 SROIE task. The archive
retains that metadata, original paired entity/text/bounding-box annotations,
and all 18 selected real JPEG scans. See the
[dataset repository](https://github.com/jsdnrs/ICDAR2019-SROIE) for attribution
and the [original task paper](https://arxiv.org/abs/2103.10213).

Allocation was fixed before OCR execution: use the first six distinct normalized
annotated merchant strings in training rows 0 through 99 for gate fitting, then
the first twelve previously unseen strings in test rows 0 through 99 for
evaluation. Uppercase alphanumeric normalization defines a merchant group. There
are no overlapping normalized merchant strings and no duplicate image hashes.
Parent-company aliases and broader receipt-template families were not
exhaustively resolved. Thus the established isolation is at the recorded merchant
string and exact-image level, not every possible business or layout relationship.

Each scan has its own actual reference annotations. Unrelated speech and video
sources from the parent experiment are not paired with these documents.
`SOURCE_MANIFEST.json` records revision, source row, selected merchant, reference,
download URL, bytes and SHA-256 for every source. The 18 scans and downloaded
source metadata total 2,261,341 bytes.

## Execution and training boundary

The model is the installed English Tesseract 5.3.4 engine. The executable and
`eng.traineddata` hashes were frozen in `FROZEN_REGISTRATION.json`, together with
every scientific Python source file, the protocol and the input manifest.
`OMP_THREAD_LIMIT=1` is passed to each OCR subprocess. The parser consumes only
recognized words, confidence values and OCR boxes. Rules select company, date,
address and total; all four rules were frozen before the formal experiment.

The base arm uses original resolution and page segmentation mode 3. The enhanced
arm uses two-times Lanczos resolution and page segmentation mode 6. Dynamic
inference first executes base OCR; if mean recognized-word confidence is below
the fitted threshold, it executes enhanced OCR and uses that answer. The search
grid is `[0, 50, 65, 80, 90, 101]`. On six fitting documents, the objective is
mean four-field exact-match fraction minus `0.01 * actual wall seconds`, with a
lower-threshold tie break. The selected threshold is **0**. Only this scalar
continuation parameter is fitted; no OCR neural weight or parser rule changes.

At evaluation, all three arms execute independently, with their order rotated
by document index. Inference takes the image path and OCR settings, with no
reference entities, transcription or reference boxes in its interface. The
answer JSON and predicted-field PNG are written and reopened before the scorer
uses the reference entity dictionary. All missing and incorrect fields remain
in the raw record. For example, the first illustrated test receipt has a
missing predicted total and an imperfect address; the supplied example is not
selected for success.

Company, date and address exact match use uppercase alphanumeric normalization.
Totals use decimal normalization where parseable. This normalization is declared
in the protocol; these are not raw punctuation-sensitive exact-match scores.
The controller and scorer are separated by their data interfaces, not an
operating-system security sandbox.

## Observed evaluation results

Each arm evaluated the same 12 documents from 12 recorded merchant groups.
The cost columns are totals for actual evaluation execution, including required
readback. CPU time is that of OCR child processes; Python/Pillow processing is
included in wall time but not the child-process CPU counter.

| Arm | Company EM | Date EM | Address EM | Total EM | All fields | OCR calls | Wall seconds | OCR CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed base | 6/12 | 7/12 | 2/12 | 7/12 | 1/12 | 12 | 11.1174 | 6.3262 |
| Fixed enhanced | 7/12 | 6/12 | 2/12 | 7/12 | 0/12 | 12 | 23.9317 | 12.0041 |
| Dynamic | 6/12 | 7/12 | 2/12 | 7/12 | 1/12 | 12 | 10.9098 | 6.2751 |

All arms have 22 exact fields out of 48, or **45.83% macro field exact match**.
The enhanced arm trades one date error for one company correction and costs
more; it does not improve overall field match. The dynamic and fixed-base
answers are identical for every evaluated document. Their small measured timing
difference is not evidence of a speed improvement: this was one run on a shared
host, and the selected gate performs the same OCR work. No confidence interval
or large-sample generalization claim is made from twelve documents.

The entire fit/test run took 54.674 seconds. Fitting used twelve OCR calls
(both settings on each fitting document); evaluation used thirty-six. The
quality shortfall, particularly address extraction, remains an open limitation.
The flags `general_complex_image_text_reasoning_proven`,
`native_neuron_integration` and `all_blockers_closed` remain false.

## Evidence and independent checks

Small repository evidence includes the frozen registration, source manifest,
results, integrity audit, an actual first-test answer/annotation pair, and the
full archive manifest and receipt. The independent audit recomputed every one
of the 36 evaluation scores from the reopened UTF-8 answers, checked both
delivered-file hashes and image dimensions, checked all input/source/model
hashes, and verified source isolation. Two focused tests cover subtotal/total
and field parsing, and prevent a missing prediction/reference pair from being
counted as an exact match.

The complete original raw archive is stored separately from Git as
`ndu_document_extension_20261026.tar.gz`. It contains all 373 original run/source
members, including all 18 actual input scans, intermediate OCR images and TSVs,
all predicted annotated PNGs, every structured answer, the gate-fit record,
per-document scores and source annotations. No output was dropped or recoded.
Every archive member was reopened and rehashed after archive creation.

- Bytes: `118906751`.
- SHA-256: `2a9a318261d8fde2a6b2e80d160756180ba5095d41e70aca0ae73cf6998f3b94`.
- Archive-manifest SHA-256: `06bafdf872520632e824fb459ccf49c891ad38123d136b2905dc79298352f837`.

The artifact location is recorded in `evidence/ARCHIVE_RECEIPT.json`; publication
can add a durable download location there without changing scientific outputs.

## Reproduction

Run from the repository root with Python 3, Pillow, Tesseract 5.3.4 and its English
language data available. The current runner records Linux child-process CPU
counters and checks the installed language path; this is a Linux research
harness. Use new output directories, because overwriting an earlier run is
deliberately rejected.

```bash
python -m experiments.multimodal_output_portfolio.repair_20261026.natural.document.fetch --output /tmp/document-assets
python -m experiments.multimodal_output_portfolio.repair_20261026.natural.document.run --assets /tmp/document-assets --output /tmp/document-run
python -m unittest experiments.multimodal_output_portfolio.repair_20261026.natural.document.test_document
```

The fetcher fails if the public dataset's declared revision/license has changed;
the archived original scans and annotations preserve the evaluated bytes.
Per-call timing and any time-dependent fit outcome must be reported for a new
run rather than assumed to reproduce the exact recorded numbers.
