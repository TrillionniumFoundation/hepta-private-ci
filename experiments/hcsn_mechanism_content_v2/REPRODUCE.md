# Reproduce the frozen four-track study

The tested worker runtime is Python with PyTorch `2.8.0+cpu`, NumPy `2.3.5`
and SciPy `1.17.0`. `ENVIRONMENT.json` and per-worker receipts record the actual
host and interpreter. Run commands from the repository root. The study uses
one numerical-library thread per worker and at most two formal workers.

## Restore the exact prepared AV inputs

The baseline commit already includes the causal feature bundle and its license:

```bash
python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_task_value_v1/artifacts/foundations001/foundations001.json \
  --destination experiments/hcsn_task_value_v1/results
```

The restore helper verifies every part, the complete archive, and every member.
It refuses to overwrite different content. The expected three NPZ hashes and
normalization identity are in `DATA_IDENTITY_VERIFIED.json`.

The restored records are prepared observations from an already observed,
actor-disjoint 48-clip cohort. No new raw decode or fresh external confirmation
is implied by restoring or rerunning them.

## Run a new reproduction without overwriting the original evidence

Choose a Python interpreter with the tested dependencies. These commands create
new output directories, retain model/data/seeds/budgets, verify the original
frozen source hashes and mechanically relocate only paths:

```bash
python -m experiments.hcsn_mechanism_content_v2.replay \
  --kind mechanism \
  --output experiments/hcsn_mechanism_content_v2/reruns/my_mechanism_run \
  --python /absolute/path/to/python --run

python -m experiments.hcsn_mechanism_content_v2.replay \
  --kind content \
  --output experiments/hcsn_mechanism_content_v2/reruns/my_content_run \
  --python /absolute/path/to/python --run
```

Omit `--run` to produce and inspect a relocated plan first. Existing output
directories are rejected. Each content adapter obtains the selected common
checkpoint only through its completed dependency's selection receipt and
matching SHA. No heldout metric is used to modify the frozen job matrix.

The 20-CPU-second runs can take different numbers of optimizer steps on another
host. Use the equal-update runs for numerical reproduction of a fixed update
budget and report the actual elapsed/CPU costs of the new host separately.

## Read the original raw evidence

Each bundle under `artifacts/` has a JSON manifest and ordered `.tar.xz.partNNNN`
files. Use the same verified helper to restore a bundle into a new directory:

```bash
python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_mechanism_content_v2/artifacts/development001/development001.json \
  --destination experiments/hcsn_mechanism_content_v2/development

python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_mechanism_content_v2/artifacts/mechanism001/mechanism001.json \
  --destination experiments/hcsn_mechanism_content_v2/results/mechanism001

python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_mechanism_content_v2/artifacts/content001/content001.json \
  --destination experiments/hcsn_mechanism_content_v2/results/content001

python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_mechanism_content_v2/artifacts/content_analysis001/content_analysis001.json \
  --destination experiments/hcsn_mechanism_content_v2/results/content_analysis001

python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest experiments/hcsn_mechanism_content_v2/artifacts/supporting001/supporting001.json \
  --destination experiments/hcsn_mechanism_content_v2
```

Bundles contain the original checkpoints, all query logits or probabilities,
labels, sample IDs, action/observation traces, selection receipts, and complete
process costs. Development evidence is separately archived, including negative
probes and the disclosed lack of complete old source blobs for some early probes.

The supporting archive already contains `results/`, `audit_source_history/`
and `overview/` path prefixes. Restore it to the experiment root shown above,
not into a new `results/supporting001` directory. It restores validation,
independent audits, the analysis replay check and the replay blueprint check.
The content analysis archive contains derived summaries; the content archive
retains all 324 initial/selected/final parameter or checkpoint files and all
717 raw prediction tables for the 108 successful workers.

Report links beginning with `results/` resolve after these archives are restored.
The original run records and checkpoints are fully recoverable; the exact
prepared AV input arrays are restored separately by the first command in this
document. This does not claim that these five bundles include all pre-decode
raw audio/video media. [EVIDENCE.md](EVIDENCE.md) lists the exact member counts,
byte totals, archive hashes, destinations and raw-versus-derived boundaries.

## Recompute summaries

```bash
python -m experiments.hcsn_mechanism_content_v2.analyze_mechanism \
  --jobs experiments/hcsn_mechanism_content_v2/results/mechanism001/jobs \
  --meter experiments/hcsn_mechanism_content_v2/results/mechanism001/meter \
  --output experiments/hcsn_mechanism_content_v2/reruns/mechanism_analysis \
  --repository-root . \
  --bootstrap 10000

python -m experiments.hcsn_mechanism_content_v2.analyze_content \
  --root experiments/hcsn_mechanism_content_v2/results/content001 \
  --output experiments/hcsn_mechanism_content_v2/reruns/content_analysis \
  --allow-heldout
```

`--repository-root .` resolves the archived receipt paths against the current
checkout when verifying output hashes. It does not modify the archived plan,
receipts, scores, or costs. Without this option, the mechanism analyzer retains
its original behavior and uses the plan's recorded root. The exact original
analyzer and its SHA-256 are preserved in `analysis_history/`.

The independent `audit.py`, `audit_mechanism.py` and `audit_study.py` recompute
their checks from raw records without importing the candidate aggregation.
`INDEPENDENT_REVIEW.md` records their exact invocation and scope.

Reproduction preserves the original limitations: three fitted seeds, two old AV
test actors, known-structure mechanism data, shared attention in content tasks,
and prepared-feature CPU timing. A zero-crossing advantage interval is not an
equivalence or noninferiority certificate.
