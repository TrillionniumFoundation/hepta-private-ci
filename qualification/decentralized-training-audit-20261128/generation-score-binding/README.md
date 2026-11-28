# Generation evaluator cached score binding

This independently covers the generation/evaluate.py entry added at commit
04968cc615f6a8c86e3ce501bb37bf53e34e0823. At that commit its evaluator is Git
blob 0120c439acbdf7a699ebec16c91cce9128b232bf, the same original bytes as the
separately audited rsicd_external entry. Its actual generation-local fit.py,
model.py and metrics.py were retrieved at the same fixed commit and hash-checked.

The patch binds cached score_file and gate to the selected checkpoint, checks
the exact NPZ bytes that it reads, loads the four consumed fields using
np.load(BytesIO(bytes), allow_pickle=False), and retains read-only arrays for
aggregation. Best/final selections of the same weights retain the existing
deduplication. Arrays are never reread from a mutable NPZ path during aggregation.

## Independent native controls

The unmodified generation entry actually reproduced the filename mismatch:
literal-109-60.npz was validated, alternate.npz was consumed 20 times, the cached
JSON means stayed unchanged, and the paired CIDEr mean became
-3.3333333333333335. Direct arithmetic from the two NPZ files matched that value.

The patched generation entry passed the same seven substantive controls in a
separate native invocation: 7/7, zero errors/failures/skips, 0.9796331760007888 s.
They cover a valid cache and duplicate best/final selections, wrong/escaping
filenames, a wrong gate, the original archive/model hash checks, and a real file
replacement at np.load entry after validation. The final test retains the
original arrays despite the backing path being replaced.

These are synthetic integrity controls, not model performance measurements.
The actual generation-local evaluator and metric code run on real small NPZ
files. Dataset/corpus and the explicitly labelled non-model identity files are
synthetic. Model construction, decoding and teacher-forced inference are
forbidden, and no training or inference ran.

Runtime: Python 3.12.3, NumPy 2.5.4, Torch 2.8.0+cpu; one CPU affinity, nice 10,
OMP/OpenBLAS/MKL/NumExpr limits of one. Total including import and baselines was
4.468538489891216 s, maximum RSS 209160 KiB. No packages were installed. These
observations are independent of the separate RSICD test invocation.

## Boundaries and reproduction

The change does not authenticate a mutable JSON-plus-NPZ pair, bind the whole
evaluation data/source context, or change cross-architecture weight-only
deduplication. The separate generation training/selection resume gaps remain
open. It does not modify any historical scientific results.

RESULTS.json includes the actual loaded generation entry, all dependency Git
OIDs and the before/after tested source hashes. The archive contains original
and tested source, genuine small control NPZs, baseline outputs, the native
unittest log and stdout/stderr. Its MANIFEST.json lists every member's size and
SHA-256, and every member was read back after compression.

Run the controls from a checkout with NumPy and Torch available:

    python -m unittest discover -s qualification/hcsn_sustained_20261128/generation -p test_generation_evaluate_cache.py -v

For the original-entry baselines, copy the archive's original/, candidate/ and
run_generation_controls.py into a fresh directory and invoke that runner. It
refuses to overwrite evidence/run-1. The archived candidates are the exact
tested bytes. No original scientific job or original data directory is needed.

## Formatting and blob policy

The original repository `just fmt` recipe ran successfully on a thin inventory
containing these two generation paths plus four previously formatted qualification
paths. All six candidate hashes remained unchanged. Its language scope excludes
qualification Python, and it reported no changed files needing formatting; this
is an execution receipt, not Python-format or full-repository qualification.
No tests were repeated after that command.

The original repository blob-size checker ran against a synthetic Git inventory
containing exactly the six proposed publication files, with its 512000-byte
default and an empty allowlist. That inventory is a size-policy control, not a
project branch or a full checkout. Its exact result is in the external
PUBLICATION_MANIFEST.json supplied for publication.
