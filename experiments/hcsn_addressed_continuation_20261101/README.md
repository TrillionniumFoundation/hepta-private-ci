# Addressed four-stage continuation

Read REPORT_ZH.md and INDEPENDENT_REVIEW.json first. This is an additive
continuation of a793d55c23a7742378b081b162252da428a9fdb2 (PR #4548).
It preserves the original scientific failures. No production default changes.

The evidence ZIP contains all five additive component directories, complete
checkpoints and raw outputs, failed attempts, verified derived inputs, and
the pinned inherited Python/JSON source required by their imports. It excludes
raw media, runtime installations, bytecode, and Git credentials. Every included
member is recorded in PACKAGE_MANIFEST.json inside the ZIP.

For public GitHub transport, clone this evidence branch including its transport
directory, then run from the repository root:

```sh
python -m experiments.hcsn_addressed_continuation_20261101.restore_transport \
  --output /tmp/HCSN_Addressed_Followup_20261101_source_evidence.zip
```

Use a fresh output path. Every part and the combined ZIP must match the exact
SHA256 and byte counts in EVIDENCE_TRANSPORT.json. No scientific source or
original output is edited by transport. The separately delivered ZIP has the
same bytes and needs no reconstruction.

After unpacking the ZIP into a fresh directory, independent arithmetic and
identity review can be repeated from that directory with Python 3.12.14,
NumPy 2.3.5 and SciPy 1.17.0:

```sh
python -m experiments.hcsn_addressed_continuation_20261101.independent_review
```

Read each component README for model reexecution. CPU PyTorch 2.6.0+cpu,
one Torch/BLAS/OpenMP thread per worker, and fresh output directories were used.
Historical baseline weights were originally trained with Torch 2.9.0; new
inference comparisons use the common current runtime. Reexecution does not
create new independent confirmation. Previously exposed actors remain exposed.

PUBLICATION_SOURCE.json records the remote preconfirmation freezes. Final
delivery publication receipts are outside the ZIP to avoid circular identities.
The complete campaign cost, attributable device energy, production deployment
and all-blocker closure remain unqualified.
