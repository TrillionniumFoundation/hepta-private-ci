# What can actually be edited in these parents?

`INVENTORY.json` enumerates the exact tensor names, dtypes, shapes, byte offsets,
hashes and ranges of the three source-bound parents. It couples those facts to
the explicitly pinned Rust control-flow contract. This is a read-only source
and checkpoint audit, not automatic discovery of arbitrary neural circuits.
It executes no model forward or fit.

The scope is the actual SmallHCSN profile used in this experiment. Other Hepta
Neuron branches or trader checkpoints may implement additional mechanisms;
absence here is not a claim that they are absent from the whole project.

| Requested object | Actual representation in these checkpoints | Meaning for an editor |
| --- | --- | --- |
| State representation | Each neuron holds full spatial probability and signed-mark mass plus boundary. Only the previous centered boundary is communicated. | A hidden state can retain information while the output has no path to it. Odd-tick raw inputs cannot reach the original receiver endpoint. |
| First-Passage / Reset | Killed semigroup for first hit, full repeated-reset generator, conservative moving-boundary remap and three-stage refractory delay. Absolute reset positions are protected F64 buffers. | There is no learned reset head. Drift/cost/recurrence affect the operators, but editing their parameters requires a separately admitted scope and the full physical/endpoint gates. |
| Call / Put | Two input choices share the same body and two classifier logits. | Neither two choices nor two logits establishes separate directional option-event channels. No Call/Put-specific tensor or payoff law was found in this schema. |
| Belief | Physical population probability and signed mark, with no observation likelihood or latent-regime posterior. | These masses cannot be relabeled as Bayesian belief. A task needing an omitted regime/history variable requires a state and observation contract. |
| Continuation Q | A local analytic resolvent, `V=(rho I-G)^(-1)r`, evaluated against current probability. | It is a frozen physical reward feature, not a learned action-value head trained on task return. The local QVI optimum is not the task's global optimum. |
| NDU value control | No learned NDU tensor in this artifact. | NDU must act as an external declared goal/risk/cost guard over available actions. It cannot manufacture a global-optimality certificate from the physical feature or a decreasing surrogate. |

There are 330 registered parameter scalars and 208 buffer scalars. Under this
exact old graph, 192 parameter scalars are structurally inactive for the receiver
score: 144 recurrent words, all 40 sender-mark words and eight `raw_boundary`
words. The remaining 138 are only *potentially* connected; that count does not
establish identifiability, useful sensitivity or trainability at checkpoint-save
time. Serialized tensor state does not recover the optimizer's trainable flags.
The shared readout biases also cancel from the exact-arithmetic choice margin,
although intermediate heads/scores and floating-point evaluation depend on them.

The experimental bridge gives previously disconnected mark coordinates an
effective output path without adding registered parameters. This is a graph
intervention, and must be represented as such in transaction identity.

## Scope is different from mathematical influence

The ordinary native profile permits only the declared readout-weight scope.
The production sender proposer permits its fixed sender drive weight and bias
scope. The scientific late-quote interface permits only four existing mark
words: flattened indices 7, 16, 25 and 34. A tensor can mathematically affect the
score while still being protected by the current editing contract. Neither this
inventory nor source access grants a wider production editing authority.

## Required semantic gates

The inventory records eight machine-readable requirements: complete function
binding, task-contract validation, reachable and live target, exact edit scope,
prospective full-forward parity for any fitted reduced objective, real endpoint
and regression verification, graph-aware restoration at the same phase, and
goal-aware KEEP selection. They are requirements for the reusable runtime
interface, not a claim that this inventory script implements transactions.

The restoration control is decisive: seed137's weights are unchanged, yet its
output changes under the bridge. A correct rollback identity therefore includes
**weights, graph, route, evaluator, input and initial/live phase**. The present
scientific evaluator reinitializes each six-tick batch; it does not exercise a
persistent trader's live state. A later live integration must bind and restore
that state separately.

The adjacent `semantic_inventory.py` creates the inventory from the frozen
source manifest and actual parent files. To reproduce, copy it into the
extracted archive's `neuron_experiments/` directory and run it there, before
creating any `semantic_inventory/` output directory. The original evidence archive and scientific outputs
remain immutable. Re-running this audit in a fresh directory does not expose a
new test set or create a new scientific result.
