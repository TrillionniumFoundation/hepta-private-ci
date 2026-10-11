# System2 content-versus-cardinality preflight

Parent source: `0e82a3a2976b7115c6ebbfb5372fbb81c8e88575`, PR #1546.
This is a train-only extension of the existing MemoryCell runner, not a new
runtime, Encoder, Reader, NDU definition, or production candidate.

## Motivation and what is not yet observed

The first native run at `aecde9ee...` produced the previously audited all-empty
advanced policies. Its answers and finite-tree solver remain unchanged.
The subsequent legacy/random/paired preflight, run **38145302766**, was still
queued at this continuation's last pre-implementation read. No result from that
run is assumed here. A workflow being queued does not establish model efficacy.

Source inspection exposes an additional possible confound: the existing paired
sampler cycles positive and negative cardinalities separately, and its first
negative example can be empty. Correctly counterbalancing work across the random
and paired arms does not itself remove within-pair cardinality information.
This is a protocol concern, not evidence that a native model exploited it.

## Small controlled intervention
`system2_content_probe.py` reuses `Continuation`, `prepare`, `TrainingCut`, and
native shared paired features. Two models start from identical weights:

- `content`: unchanged paired feature vectors.
- `content_erased`: zero vectors of the identical shape, at both fit and inspection.

Every trained hit/miss pair uses the same question, the same nonzero number of
windows, and exactly one candidate replacement. The two arms use the same pair,
labels, presentation order, optimizer updates and neural shapes/calls. Actual
latency and zeroing overhead are not declared equal. The fixed top-four proposal
and maximum three selected windows remain unchanged.

The erased arm keeps the trainable projection bias, recurrence and critic, so it
can learn a function of path length. But at fixed cardinality its two inputs are
identical. With prediction p for both, balanced binary cross-entropy is
`-(log(p) + log(1-p))/2`. It cannot rank the pair using length alone. The report
requires its equal-size margins to be exactly zero and awards a tie half credit.
This is an intervention check, not a claim of 50% native task accuracy.

Rows with no equal-size positive/negative opportunity remain in the census as
ineligible. They are not trained as unanswerable questions. Inspection still
includes the empty path and free argmax: no nonempty choice is forced.
Native source membership remains weak supervision, NOT joint semantic sufficiency.

## Observation and progression
The report separates pair ranking, free-choice weak support, empty choices,
question-macro and family-macro aggregation, and all ineligible questions.
Pairs sharing a question or source family are not independent observations.
A fixed training comparator uses the maximum frozen score in each evidence set;
this is a ranking reference, not a claim that it is the best end-to-end RAG.

A training progression request requires improved pair ranking over initialization,
the erased arm AND that frozen ranking reference, plus an improved free-choice
training hit count. Even then the next gate is fresh confirmation and Reader
controls; all adequacy, task-superiority and production flags remain false.
The earlier three-way receipt is also tightened: a paired model that beats only
initialization but does not beat its work-matched random control cannot advance.
Neither change alters the earlier three-way optimizer or sample generation.

## Resource boundary and reproducibility

`system2_native_trial.py --development --content-preflight` takes an explicit early
return before Reader construction. It encodes only the predeclared general Cell
training questions (up to 24 of the inherited 48), not test/transfer queries.
Source-family separation and forbidden evaluation roots remain checked.
The three 16/32/48 curriculum cut points are inherited; both arms are freshly
initialized at each cut. There are zero planned policy answers and Reader calls.
The Reader-first preflight and eight-arm entry remain available in their original
modes. No missing human condition is relabeled as completed or accepted.

Training feature tensors, source-membership indices, original feature seals,
training admission metadata, successful model states, and every pair update are
saved under the existing run artifact. Safetensors are reloaded and compared for
exact tensor parity. These exports enable later replay without re-encoding, but
are not an authenticated production cache. Do not treat parameter-only reload as
permission to ignore the saved source lineage or a new revocation.

The existing workflow still runs all discovered MemoryCell regressions and the
pinned original-result audit. Its new execution command selects the content-only
mode instead of repeating the old 64 available Reader controls. Staging may still
transfer the inherited combined model archive; zero Reader calls is not zero
end-to-end network or preparation cost.

Local evidence: **75 tests passed**, including 24 added regression/integration
checks and the original pinned native archive audit, with torch 2.10.0+cpu.
The runner integration uses isolated fixture ports, NOT real pretrained models.
Python compilation passed. Full repository tests and pinned hosted torch 2.5.1
execution require the new exact-head workflow. Local `just fmt` could not run
because `just` is absent; no Rust source was changed and no CI gate is waived.

```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_native_trial.py \
  /path/to/memory-inputs /path/to/pinned-ranker /new/output \
  --development --content-preflight
```
