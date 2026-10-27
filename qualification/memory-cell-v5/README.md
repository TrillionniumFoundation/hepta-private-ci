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

`PROTOCOL.json` declares the five formal seeds, six bounded candidate models,
all quality thresholds, comparison arms and denominator rules. Formal execution
must wait for a remote source commit and a `FREEZE.json` binding the exact source
files, protocol, held seal and candidate-selection procedure. Only training and
selection data may choose a candidate or rejection threshold. The entire `held`
directory is already sealed and must not be reformatted or edited.

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
