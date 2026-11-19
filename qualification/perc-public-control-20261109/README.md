# Public-feature acquisition control — 2026-11-09

**Engineering control executed; scientific qualification and adoption remain HOLD.**
The earlier real encoder and held-out campaign remain unchanged at #5537. This
stage adds a learned control that uses public geometry and acquired OCR, with no
backbone, projection, latent access or encoder cost. It isolates a missing control;
it does not establish latent benefit.

## Implementation and boundaries

`document_actor.execute(..., mode="public_active")` requires a zero-latent head
before I/O, emits a comparator record, and rejects encoded or encoding-charged
observations on every read. `Collector(dataset, None, None, output)` supports an
actual no-model runtime and rejects neural execution before source I/O. Existing
global/dense neural defaults and native capacities stay unchanged.

`python -m perc1.document_public_control --dataset-dir DATA --output FRESH`
collects fresh TRAIN/DEV OCR pairs and fits the same deterministic gain/cost ridge
learner. It validates the panel/dataset identity, pins training-target content and
bytes before fitting, freezes the head before DEV execution, and checks source
stability. Confirmation captures and the sealed evaluator are never opened.

## Actual development execution

Both retained runs used the same existing 64 TRAIN / 16 DEV source documents;
their public metadata also retains the untouched 32-document confirmation group
registry. Each run collected **160 paired labels**, then executed **48 DEV tasks**
across public-active, direct-ROI OCR and initial OCR. Each retained **304 OCR
observations and zero encoder calls**, with no collector failure.

| Final provenance-corrected DEV run | Correct | Total online proxy cost |
| --- | ---: | ---: |
| Public features + learned active | 12/16 | 3,202,546 |
| Direct requested ROI + OCR | 12/16 | 1,643,028 |
| Initial OCR only | 0/16 | 1,648,459 |

Public-active costs **1.949173×** direct ROI in this DEV run. The first run had the
same correctness outcomes and a cost ratio of 1.953554×. The second run added
panel/label identity and source-stability checks; neither run tuned on or reran
confirmation tasks. These are development repetitions, not independent training
replicates. DEV participates in calibration, so no confirmatory interval or
policy benefit is claimed. Different machines and timings prohibit causal cost
comparison with #5537. The proxy measures observed online time and bytes; listed
setup components do not cover all startup, evaluation/bookkeeping, money or energy.

## Evidence and remaining gate

[DEV_V1.json](DEV_V1.json), [DEV_V2.json](DEV_V2.json), [FORMAT.json](FORMAT.json),
[VALIDATION.json](VALIDATION.json) and [PRIVATE_EVIDENCE.json](PRIVATE_EVIDENCE.json)
retain aggregates, source hashes and archive identity. The final targeted gate
passed **58 tests, zero failures/skips**. Required `just fmt` passed; all six tested
Python ASTs were preserved. Historical native and neural-checkpoint tests were not
rerun. Private evidence retains raw OCR, TRAIN/DEV inputs, heads and both attempts;
no raw document payload or target text is published here.

Keep direct-ROI acquisition for the present public-coordinate task. Next scientific
work needs fresh semantic-localization sources without answer coordinates,
public-only and latent controls under matched opportunities, cross-template groups,
independent training repetitions and complete paid-cost utility. Production Cell
source/budget ownership and the full four-family confirmation gate remain open.
