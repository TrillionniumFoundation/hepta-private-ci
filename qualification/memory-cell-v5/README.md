# V5 targeted language-addressing study

This is a new bounded research increment. It uses actual learned word/character
features and linear classifier weights, a separately authored held corpus, and
four recovered parameter memories connected by a previously learned typed
layout. It targets the language-addressing failure observed in the earlier
study. It does not claim to restore the missing original V4 source or raw run.

## Experimental boundaries

The six supported operations are the value at the supplied month, its immediate
predecessor, current minus preceding value, and the mean, range or maximum of
the three-month window ending at that month. Entity and date are explicit input
slots. Other operations are out of scope. Type ports and arithmetic primitives
remain supplied capabilities.

Training/selection and new held wording are owned separately. The held corpus
contains 216 assistant-authored English utterances: 144 known and 72 near-OOD.
It is neither real-user traffic nor independent human annotation. It is reused
across four numerical domains and five training seeds; these repetitions do not
create additional independent language examples.

The frozen saved numerical factors and layout come from the recovered original
V4 seed-401 artifacts. Their format is read by byte-identical recovered V3
modules. Their original training cost and historical identities remain explicit;
this increment does not retrain those memories or the graph.

The main arm loads only parameter memories and address metadata. A separately
loaded ordinary exact codec plus a supplied planner is the strong comparator.
Oracle routing is a declared grading control. Removing cross-cell edges and
permuting compatible nodes measure actual dependency on composition.

## Freeze and evaluation

`PROTOCOL.json` declares the five formal seeds, eight bounded candidate models,
all quality thresholds, comparison arms and denominator rules. Formal execution
must wait for a remote source commit and a `FREEZE.json` binding the exact source
files, protocol, held seal and candidate-selection procedure. Only training and
selection data may choose a candidate or rejection threshold. The entire `held`
directory is already sealed and must not be reformatted or edited.

The original six-candidate development run and the two-candidate negative-family
revision both failed the required coverage/risk tradeoff. Their complete actual
fits, raw predictions and source snapshots are retained in the two `evidence/`
archives. `DEVELOPMENT_ROUTING.md` explains those results and the bounded revision;
`V5B_PREDECLARATION.md` records the mechanism before the four additional fits.
No third candidate family was added to this increment.

After final source formatting and remote source delivery, the reproducible order is:

```bash
python -m maintenance.freeze source --commit <verified-source-commit>
# Commit and verify FREEZE.json remotely before formal training.
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  python train_routing.py --output results/formal/routing \
  --seeds 1019 1021 1031 1033 1039 --source-commit <verified-source-commit>
python -m maintenance.freeze selection --training results/formal/routing
# Commit and verify SELECTED_MODELS.json and selected model artifacts remotely.
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  python evaluate_joint.py --routers ROUTERS.json --assets assets \
  --held held/queries.en.json --output results/formal/joint --freeze FREEZE.json
```

The evaluator validates the selected artifacts against the complete eight-candidate
selection receipts and the declared selection rule before it opens held language.
The saved directory map is local to an execution; a relocated copy must regenerate
that map while retaining the same model file identities. A replay after publication
is a reproduction of this fixed held corpus, not another independent test.

Restore a delivered evidence archive into a new directory with:

```bash
python maintenance/evidence.py unpack --source evidence/v5a-development \
  --destination /tmp/v5a-evidence-restored
```

The utility verifies every part, the concatenated archive and every extracted file.
Archive transport is not claimed as an improvement in the parameter-memory system.

The development seeds are 8011 and 8017. Formal seeds are 1019, 1021, 1031, 1033
and 1039. Fresh processes receive only utterance/entity/date inputs and saved
artifacts, never grader labels or numeric targets. Fresh-process execution is
not a claim of operating-system or filesystem isolation.

Results will report correct accepted known coverage, OOD false acceptance,
numeric exactness and ordered provenance, actual edge ablations, oracle gaps,
all trained candidates, serialized storage, expanded numerical arrays and
observed execution costs. Failure remains a failure; the thresholds will not be
lowered after held evaluation. A scoped success would not by itself establish
general memory, weight erasure, distributed maintenance, universal structural
advantage, or production admission.
