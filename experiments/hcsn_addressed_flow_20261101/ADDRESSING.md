# Shared addressed content architecture

The predecessor stored one global content moment per physical state. Its query
decoder had to infer key/value correspondences from that compressed global
mixture. This revision gives both cores the same explicit addressed content
and relation memories, so the experiment can separate repairing content capacity
from any benefit of marked CTMC dynamics.

## What is supplied and what is learned

Both cores receive the unchanged 24-dimensional symbolic token. The architectural
prior identifies the supplied fields: four A addresses, eight value symbols,
four event kinds and four B aliases. No target, dependency position, answer,
actor, split identifier or future observation is added. Address vectors are
trainable, with tied read/write embeddings. Soft routing initially favors an
equal key, as key comparison in attention does. This is a substantial shared
addressing prior and is not a discovery of a general unstructured parser.

Event-kind gates begin with equal logits for writes and distractors. Their
selectivity, value representation and final class decoder are trained using the
same task loss. Typed presence masks suppress content writes that have no value
field and relation writes that lack either address. A relation write stores the
learned A address distribution under the learned B address distribution. A B
query reads that relation and then reads content. This fixed two-hop composition
is also an explicit shared prior. It does not supply the random episode's
mapping or any answer; the observed bridge tokens supply the mapping.

## State and time semantics

Each of four A addresses stores five physical-state-conditioned moments of a
16-dimensional learned value plus one matching occupancy moment: 340 scalars.
Each of four B aliases stores five moments of its four-dimensional A address
distribution plus occupancy: 100 scalars. Both cores have these same 440
content/relation scalars. Flow additionally keeps its five-state probability and
two control coefficients. Parameter counts and transient kernel memory are
reported separately rather than described as exactly equal.

Flow uses the predecessor's actual `ContentModel._flow_matrices` implementation:
the same full probability transition, marked content transition, and marked
moving-boundary remap. Ordinary memory uses five learned exponential decay
rates. Both cores evolve over the interval before reading the current query.
The current observation can write or change policy only after that read.
Unobserved placeholders consume physical time without changing policy or
writing. Negative or nonfinite durations are rejected.

For memory moments `M[a,s,d]` and occupancy `W[a,s]`, the default read normalizes
by the matching address occupancy `sum_s W[a,s]`. It exposes both the normalized
sum and the normalized state-conditioned values to the decoder. Consequently,
common scalar event attenuation cancels from content identity; confidence and
conditional state shape can still change. This normalization is deliberate
content preservation. A successful content result cannot by itself establish
useful first-passage, risk, recovery or reset dynamics. The public
`normalize_occupancy=False` setting and `intervention='no_marks'` permit
same-weight sensitivity analyses; those are not retrained necessity tests.

## Evidence boundary

`addressing_checks.py` tests causal reads, missing-observation behavior, batch
independence, numerical time subdivision and nonzero finite gradients on
development inputs. These checks establish executable semantics, not content
quality. `dev_smoke.py` retains all six development trials with shared initial
content weights, data, fixed budgets and costs. Final capability conclusions
require the separately frozen confirmation campaign. Neither this symbolic
architecture nor a passing synthetic binding task establishes real audiovisual
front-end quality or a foundation-model capability.
