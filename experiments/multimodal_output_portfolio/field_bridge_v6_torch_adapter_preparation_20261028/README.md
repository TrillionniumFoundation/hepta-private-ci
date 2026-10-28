# CPU Torch/SGD adapter preparation

**NOT_REGISTERED / NOT_EXECUTED.** Only small synthetic engineering tests run
here. No scientific assets, frozen learning forward, bank, endpoint, fit or fresh
holdout are loaded or executed. The original V5 scientific **FAIL**, rejection
and no-admission status remain unchanged. The nine foundation files are unchanged.

## Supported state and explicit limits

The adapter uses the frozen foundation's typed branch-state schema and literal
codec. It captures named CPU parameters and buffers, `None` versus zero incoming
gradients, complete declared SGD state and parameter groups, ordered ID/name
mapping, CPU/Python/NumPy global RNG, and separately named generators. Named
generators may be CPU `torch.Generator`, `random.Random`, NumPy `RandomState`, or
NumPy `Generator` with the listed supported bit generators.

Configuration, `requires_grad` flags and module train/eval modes are immutable
under this schema. Drift is rejected before writing. Structure, plain Python
configuration attributes, optimizer defaults/static fields, frozen base and both
reference models are hashed from actual objects. Context inputs and the original
guard values are independently bound. The caller must supply the complete
context and architecture declaration; this cannot discover omitted external
inputs, files or program state.

The supported optimizer is stock CPU SGD with the complete foundation group
fields. Differentiable or fused SGD, schedulers, sparse/meta/noncontiguous tensors,
shared storage, tied modules, hooks, tensor hooks, custom tensor attributes and
unregistered array module/optimizer attributes are rejected. Buffer/momentum/gradient autograd graphs are also
rejected. Shared storage is checked across the live model, references, context
and guard; RNG checks include underlying NumPy BitGenerator owners and globals.
No general Python object graph or arbitrary optimizer state is serialized.

## Restore contract

1. Decode and verify the exact record and separately held environment identity.
2. Check the actual target's immutable dependencies, runtime, structure, tensor
   inventories and SGD parameter order. Validate all recorded groups with stock
   SGD constructors, and all RNG states with independent RNG instances.
3. Allocate prepared values and a rollback snapshot before the first write.
4. Copy into existing parameter/buffer objects, restore gradients, SGD
   state/groups and RNG, then recapture and compare the entire literal record.

Configuration, identity, type and invalid-RNG failures are tested to leave values,
object references, RNG and parameter version counters unchanged. The adapter
does not call `forward`, `backward` or `optimizer.step`; those toy operations are
only in the test program and are counted separately.

On an unexpected error during application, the adapter attempts rollback,
preserves the original optimizer containers and gradient references, and raises
`RestoreError` with explicit public-state and autograd-version results. It does
not promise recovery from process death, allocation failure during rollback or
concurrent mutation. A scientific runner would still need its own durable
failure evidence and complete cost ledger.

**Use only between steps, with no pending autograd graph and no concurrent
writer.** A successful `copy_` changes PyTorch version counters. The public API
does not restore those counters; the adapter reports this explicitly. A graph
created before restore is outside the contract. Merely being a leaf parameter
does not prove that no external graph refers to it.

## API and verification

Construct `Adapter` from the live model/SGD, immutable references, complete
context/guard, named generators and binding. `binding.runtime_sha256` must equal
`codec.digest(runtime_descriptor())`. `capture(cursor, remaining_schedule)`
returns a foundation record; `branch_state.seal(record, environment_sha256)`
produces literal bytes. `restore(raw, expected_sha256, maximum_bytes)` returns the
logical cursor/tape to the caller. Actual work counters are external and are
never rolled back.

Run the bounded toy suite with the already installed runtime and a new report
path; report writes are exclusive:

```sh
python -I -B experiments/multimodal_output_portfolio/field_bridge_v6_torch_adapter_preparation_20261028/tests.py --report /tmp/v6-torch-adapter-new.json
```

The main replay test uses two 2-element parameters, one frozen scalar, a small
integer buffer and dropout. It performs a real toy backward/SGD step, restores a
checkpoint, then repeats the step. Full output, parameter, buffer, optimizer,
gradient and RNG bytes must match. Each checkpoint is capped at 64 KiB and its
temporary file is removed by the test fixture. This proves that toy transition;
it does not prove replay of the scientific learning kernel or field-control
efficacy.

`PREPARATION_REPORT.json` records each test attempt, including initialization and
validation failures, the final result and exact toy operation counts. No failure
is converted into a scientific success. Real candidate shape/cost bounds,
scientific kernel integration, historical regression and existing storage gates
remain separate work. The proposal's minimum **2 GiB `f_bavail`** condition is
unchanged; this preparation does not authorize a candidate run or raw upload.
