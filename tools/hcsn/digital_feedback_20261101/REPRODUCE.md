# Reproduction and custody

Start from this branch, whose parent is the immutable PR #4560 head
`72917c2a32d79a63071a074b6a57d98d331f7fb8`. The inherited 40-file scientific
inventory is checked against that study's published `SOURCE_FREEZE.json` before
every new worker. No parent scientific file is edited.

The recorded environment uses Python 3.12, NumPy 2.3.5, SciPy 1.17.0 and
PyTorch 2.15.0+cpu with one numerical thread per worker. The CPU interrupt uses
Linux `ITIMER_PROF`. Set the standard numerical-library thread counts to one.
The session provided PyTorch as an existing package tree at
`/tmp/hcsn-torch-runtime`; an ordinary installation of the recorded versions is
also sufficient. Do not substitute a GPU training budget.

From the repository root, use `python -m` for the namespace modules. The phase
commands below intentionally use new destinations; existing results are never
overwritten or silently pooled.

```bash
python -m tools.hcsn.digital_feedback_20261101.study development \
  --root /absolute/new_development \
  --protocol tools/hcsn/digital_feedback_20261101/protocol_development.json \
  --workers 3
```

Development results determine the new independent-fit plan by the registered
noncentral-t calculation, using the marginal one-sided 90% variance bound and
the stated independent-normal-fit and variance-transfer assumptions. A binding
resource cap is a precision shortfall, not evidence that the target power was
achieved. Formal `protocol.json` and source identities are published before any
formal fitting.

```bash
python -m tools.hcsn.digital_feedback_20261101.study train \
  --root /absolute/new_training \
  --protocol tools/hcsn/digital_feedback_20261101/protocol.json --workers 3
```

The final complete optimizer update is retained. CPU-limited training is not
bitwise repeatable across machines: the number of complete updates may differ.
Published model bytes, full update/feedback receipts and physical parameter
identities are therefore the authority for this exact confirmation.

All formal models, independent ridge coefficients, actual training data and
process receipts are hashed into `MODEL_MANIFEST.json`. They are published and
read back before `SEALED_MODELS.json` permits confirmation. Fresh IID/OOD worlds
are then generated from a new namespace; old confirmation observations are not
reused as fresh evidence.

```bash
python -m tools.hcsn.digital_feedback_20261101.study confirm \
  --root /absolute/new_confirmation --training /absolute/restored_training \
  --seal tools/hcsn/digital_feedback_20261101/SEALED_MODELS.json \
  --protocol tools/hcsn/digital_feedback_20261101/protocol.json --workers 3
```

Large artifacts use archives of unchanged file bytes. Each archive has a
`MANIFEST.json` with file SHA256s, part SHA256s and whole-archive identity;
stored base64 parts are below the existing repository blob limit. Restore each
published archive to a fresh destination:

```bash
python -m tools.hcsn.digital_feedback_20261101.archive restore \
  tools/hcsn/digital_feedback_20261101/archives/ARCHIVE_NAME \
  /absolute/fresh_destination
```

The final archive index records destination roles. Training receipts preserve
the original absolute world paths as provenance. The confirmation entry point
loads sealed confusion/model/support artifacts and generates its own fresh
world folders; it does not replay unread training packet paths. Raw recorded
confirmation can be audited without generating any new worlds.

`audit/independent.py` recomputes numerical outcomes/statistics from raw records
without importing the project summarizer. Authorship and the separate code
review are disclosed; it is not an external peer review. All attempted workers,
including failed or CPU-noncompliant ones, remain in the archive and cost ledger.
