# V6 held language contract

This corpus was authored by the independent evaluation assistant after receiving
only the six operation definitions. The author did not read V6 training,
development or selection wording. It contains assistant-authored synthetic
requests, not human annotations, natural traffic or a statistically representative
sample. English and Chinese variants share semantic families. No claim of
independence is made for variants, repeated entities, seeds or domains.

The corpus has **288 distinct templates**: 192 supported requests (32 for each
operation; 16 English and 16 Chinese), and 96 unsupported requests (eight for
each of 12 families; four English and four Chinese). There are 24 supported
families and 12 unsupported families. All 288 belong in the denominators.

## Inputs and operation semantics

The serving request supplies text, entity, `at` and `since` separately. The text
may interpolate `{entity}`, `{at}` and `{since}`. These slots provide identity
and dates, not correct operation labels, numeric answers or procedure choices.
Omitting a slot in the wording does not make a request unsupported: its structured
field remains available. Entity/date extraction from unconstrained prose is not
tested. The two historical cutoffs must satisfy `since < at < latest-event-time`
in the evaluation fixture. This prevents an unsupported two-history comparison
from becoming equivalent to the supported current-minus-history operation.

| Operation | Supported result |
| --- | --- |
| `current` | Latest valid event value in the bound snapshot. |
| `history` | Last valid event value at or before `at`, inclusive. |
| `semantic` | The single stored stable property associated with the entity. |
| `procedure` | The stored finite procedure/program description, without execution. |
| `change` | Current event value minus the value effective at `since`, preserving sign and original units. |
| `apply` | Execute the stored procedure on the current event value and the stored semantic property/parameter. |

All known requests assume the fixture contains the addressed valid records and
required registered procedure. A memory-read failure still counts as a known
miss; it never changes the request's label to unsupported. A trained model's
prediction is not made correct by finding an unrelated source with the same value.

Unsupported families are forecast, causal attribution, unregistered statistics,
new arithmetic, differences between two historical snapshots, cross-entity
ranking, counterfactual inputs, external mutations, invention of new procedures,
ambiguous operations, multiple independent outputs, and measurement uncertainty
not represented by the stored data. These are limits of this declared six-operation
reader; they are not claims that a more general memory system should reject them.

Some unsupported queries mention supported operations as subparts. The grader
expects rejection of the complete unsupported request, rather than answering only
one familiar subpart. Returning stored instructions and executing those instructions
are different intents. Procedure retrieval does not authorize an external action.
The primary unsupported-error denominator measures accepted routing, including
requests later blocked by a failed memory read. Final answer acceptance is also
reported. This choice was fixed before source/model freeze, not after results.

## Sealing and interpretation

`queries.json` is the frozen source of requests. `author_corpus.py` preserves their
authorship and reproducible serialization. `SEAL.json` binds both and this contract
plus `PROTOCOL.json`. The training owner may inspect counts and digests but must
not read the wording until the source, candidate/selection protocol and selected
model artifacts are frozen. No result-dependent wording or label changes are
permitted. If a genuine semantic flaw is discovered later, retain the original
rows and report the flaw separately; changing the corpus requires a new named
study and a newly independent evaluation set.

Gold values and event provenance come from the frozen fixture/grader, not from
the model, router or graph executor. The independent results auditor recomputes
canonical value hashes and scoring from those recorded golds and raw outputs. It
requires the complete seed/domain/arm plan so missing entire cases cannot disappear.
It does not independently
authenticate external fact truth, original process timing or all operating-system
I/O. The experiment does not establish novel primitive discovery or unrestricted
language understanding.

Repeated execution is a reproducibility check. After publication, this corpus
cannot be reused as a fresh held test of a model tuned using its results.
