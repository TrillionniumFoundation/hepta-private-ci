# PRED one-step numerical shadow wiring

Depends on the shared snapshot validator in #5646. A host can supply one frozen
snapshot, a SHA256-pinned Model checkpoint, an explicit ordered feature/encoding
contract and candidate action columns. The model contract also binds the exact
32-class support, success definition, duration/cost units and declared model
origin. Native training declarations require an evidence reference. None of
these declarations authenticates a source or proves that the mapping is valid.

`shadow_predict` reads the bounded checkpoint bytes once, checks ZIP/NPY headers
and exact bounded model member shapes before numerical loading, then loads those
same bytes. The supported profile limits each array dimension to 256 and rejects
object/structured arrays; this is not a general model-format loader. Each shared
observed prefix is encoded once (the single-step MLP uses only its final row).
Only the supplied heads run. A single candidate costs one head call. Candidate
queries cannot mutate the observed state or model/optimizer numerical state.

Create-only output binds snapshot, checkpoint, model, contract and schema hashes;
records logits/probabilities, actual state/head counts, and CPU/wall time. The
measured scope includes validation, checkpoint hashing/loading, template checks,
and inference. It excludes output serialization/hashing, writing/fsync, owner
collection, training, transport, energy and money. `physical_cost_complete` is
false. The output executes no action, reads no joined label and computes no
counterfactual utility. Source replay time is not action execution time.

The scoped package passed **112 tests**, including nine new shadow tests.
Four real NumPy model implementations are saved, loaded and compared with their
actual forward calls, using random initialized fixture checkpoints. Tests also
cover immutable state, single-head counts, hash/schema/identity/contract errors,
nonfinite inputs/parameters/outputs, a replaced path after byte pinning,
malformed small NPY headers, create-only output and refusal of readback input.
Repository just fmt and Ruff passed with the tested ASTs unchanged. Exact source
and original validation are adjacent. No native-history model was trained and
no live owner, real effect label or independent task-benefit run was collected.

The historical 189-fit originals remain unlocated; a new execution cannot be
reported as recovery of those originals. The two used confirmation sets remain
sealed. Instability attribution, real labels/units, readback-driven live action
selection, the matched Fixed1/short-horizon trial and all-in independent net
decision utility remain open. HOLD and production flags remain unchanged.
