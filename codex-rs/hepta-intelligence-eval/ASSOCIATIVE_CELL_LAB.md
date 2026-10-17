# Experimental associative MemoryCell: source → parameter → read

This **research-only** addition lives under existing `learning.eval`; it does not
install a model, change the selected production MemoryCell, alter any owner state,
create a second memory service, or grant fact/effect authority.

## Reproduce

From the repository root (CPU PyTorch is the only required runtime package for
this stand-alone slice):

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_associative_cell.py' -v
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/associative_cell_trial.py
```

The controlled fixture is deliberately synthetic. A vector containing an
observable type token and numerical cue is paired with a different vector for
semantic vs procedural synthetic operators. These are **not** claims about a
pretrained Encoder, natural language, semantic citation entailment or external
independent sources.

## Functional boundaries

- `Experience` contains bounded `(cue, value)` vectors, encoder identity, type,
  source family/root/scope and observation time. The caller is responsible for
  authenticating the sources and permission to learn from them. These tuples are
  **approved input to an experiment**, not a durable evidence record.
- `TrainingCut` rejects future, held-out, wrong-scope, wrong-encoder, wrong-type,
  revoked and duplicate examples before the proposed update. Validation of its
  self-attested digest **does not** independently authenticate the admission.
- `AssociativeCell` is an actual small trainable rank-bounded two-layer
  tanh memory (`tanh(W_down × cue) × W_up`) with no biases. One low-rank
  cell has `2 × dimension × rank` independent parameters. Current selected
  objects are immutable across `propose_update`: training creates a new
  candidate with no-momentum SGD. `read()` receives **no answer** and returns
  only a raw latent vector, **never source evidence**.
- An artifact contains the weights, source-root lineage, encoder identity,
  scope, fixed shape, predecessor, generation, counters and no raw cue/value
  pairs or stored answer lookup table. Clean-process reload verifies exact
  artifact bytes, dimensions, tensor finiteness, scope, roots and revocations.
  A root withdrawal denies the whole affected artifact and all split children;
  there is **no proven selective machine unlearning**.
- A rank `2r` mixed parent can be partitioned into two rank `r` typed children.
  **Child1(x) + Child2(x) = Parent(x)** immediately after split, but selecting
  just one child does **not** preserve the parent's prediction. Split is only a
  candidate; production cutover is not implemented or authorized.
- The `ExperimentalBank` exposes an explicit switched-kind ablation. It is
  isolated from `neuron.runtime`, `inference.control`, `cognitive.read` and
  the existing owner/selector contracts, and has no tool or effect access.

## Comparison controls and measured accounting

The sample source-family/root train/future cuts are disjoint. No answer or
`value` appears in `ReadQuery`. Training and future evaluation use precisely the
same encoded cue and explicit type for all arms; the mixed model does not lose a
feature which the typed model gets privileged access to.

| Arm | Meaning |
| --- | --- |
| `frozen` | no training of the initial rank `2r` parent |
| `same_capacity_shared` | trained rank `2r`, same total parameters and number of SGD sample updates as typed |
| `equal_touch_shared` | rank `2r`, same approximate parameter touches as typed, fewer sample updates |
| `typed_split` | two rank `r` heads, explicit route and matched total parameters |
| `swapped_type_route` | exact typed parameters, deliberately incorrect route |

The report separately counts parameters, SGD sample updates and parameter-touch
estimates. Touches are **not** FLOPs, wall-clock training cost or energy usage.
The experiment is a narrow deterministic numerical mechanics fixture, not an
independent memory benchmark. Its vector MSE is **not** answer accuracy or a
semantic citation precision measurement. Even if the typed arm wins on this
fixture, `production_qualified`, `statistical_superiority`, and all claimed
external-model/strong-RAG checks remain false.

## Next admission work (not implemented by this slice)

1. Pass real frozen encoder receipts through the already registered
   `inference.control` feature boundary and train only from independently
   admitted source/answer operations. Do not infer source or permission from
   tensor digests.
2. Prove reader capacity first using empty, strong retrieval, independently
   sufficient-evidence and premise-deletion controls; keep reader gains separate.
3. Compare artifact-only parameter recall with cached, independently tuned
   strong RAG and with indexed single/multihop/temporal evidence selection.
4. Pre-register source-family-disjoint future tests, fixed total lifecycle
   costs, repeatability, measured tail latency, abstention, correction and
   real deletion/recovery. Make split vs static/no-split and graph edge lesions
   matched for information, parameter capacity and actual computational budget.
5. Use `learning.artifacts` for immutable tensor manifest ownership,
   `learning.operator` for real training, `learning.plasticity` for proposals,
   `neuron.runtime` for scoped checkpoints, and existing memory owners for
   evidence and revocation. No registry/wire/signer/promotion change here.

This document and the test receipts are **not** independent acceptance or a
permission to connect a new producer to production.
