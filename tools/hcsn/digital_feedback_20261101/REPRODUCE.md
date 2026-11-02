# Reproduction and custody

Start from this branch, whose parent is the immutable PR #4560 head
`72917c2a32d79a63071a074b6a57d98d331f7fb8`. The inherited 40-file scientific
inventory is checked against that study's published `SOURCE_FREEZE.json` before
every new worker. No parent scientific file is edited.

The recorded environment uses Python 3.12, NumPy 2.3.5, SciPy 1.17.0 and
PyTorch 2.15.0+cpu with one numerical thread per worker. The final CPU control uses synchronous process-CPU checks at bounded work
boundaries. It does not arm `ITIMER_PROF`; actual native-call overshoots are
measured and rejected. Set numerical-library thread counts to one.
The session provided PyTorch as an existing package tree at
`/tmp/hcsn-torch-runtime`; an ordinary installation of the recorded versions is
also sufficient. Do not substitute a GPU training budget.

From the repository root, use `python -m` for the namespace modules. The phase
commands below intentionally use new destinations; existing results are never
overwritten or silently pooled.

```bash
python -m tools.hcsn.digital_feedback_20261101.study development \
  --root /absolute/new_development \
  --protocol tools/hcsn/digital_feedback_20261101/protocol.json \
  --workers 3
```

This runs a new development attempt with the final eight-gate implementation.
It is not a replay of DEV001 or DEV002. Those historical attempts used the
six-gate development protocol and their corresponding archived source snapshots;
restore each source snapshot with its original protocol to reproduce that
historical implementation. Keep such reruns in new destinations and label them
as reruns, not independent confirmation.

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

The archive format also supports deferring duplicate `*_audits.json.gz` tables
when an archive explicitly contains `DERIVED_DIAGNOSTICS.json`. That manifest
records the exact original size and SHA256. All raw decisions, trained support
records, actual outcomes and quality summaries remain verbatim. Only for such
an archive, recreate the derived tables before running the full numerical audit:

```bash
python -m tools.hcsn.digital_feedback_20261101.orchestration.rebuild_diagnostics \
  --fit /absolute/restored_confirmation/fit_6003 \
  --training-fit /absolute/restored_training/fit_6003 \
  --output /absolute/restored_confirmation/fit_6003
```

The command rejects any mismatch with the original derived table hashes. A
same-runtime cold reconstruction was checked against the original byte stream;
cross-runtime gzip/NumPy byte identity is not assumed.

`audit/independent.py` recomputes numerical outcomes/statistics from raw records
without importing the project summarizer. Authorship and the separate code
review are disclosed; it is not an external peer review. All attempted workers,
including failed or CPU-noncompliant ones, remain in the archive and cost ledger.

## Full confirmation archives for this run

This run uses the complete archive mode: both `iid_audits.json.gz` and
`ood_audits.json.gz` are included verbatim alongside all raw episode/probe
records, cohort files, quality summaries and decoder results. No derived table
is deferred, so the reconstruction command above is not needed for this run.

After the confirmation group's `LAUNCH.json` exists, incremental packaging can
run alongside the remaining workers:

```bash
python -m tools.hcsn.digital_feedback_20261101.orchestration.live_pack \
  CONFIRMATION_GROUP \
  --seal tools/hcsn/digital_feedback_20261101/SEALED_MODELS.json \
  --include-control --watch
```

Replace `CONFIRMATION_GROUP` with the group directory name under this study.
The helper requires the confirmation stage, current frozen source/protocol,
the registered fit set and the same seal/model publication recorded by every
completed worker. It packages a fit only after its FINISHED record and successful
external process receipt exist, then cold-restores and verifies every file.
The control archive waits for all 32 registered fits to finish and for the
controller to have no active or pending workers. The helper writes cumulative
packaging evidence and local immutable-blob metadata; it performs no upload.
