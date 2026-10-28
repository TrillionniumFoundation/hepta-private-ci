# V6 stock GRU adapter preparation

**NOT_REGISTERED / NOT_EXECUTED.** This is a bounded engineering extension for
the existing CPU Torch/SGD state adapter. It does not register or execute the
proposed scientific candidate. The original V5 scientific result remains FAIL,
admission remains false, and the historical endpoint regression remains open.
No scientific model, asset, endpoint, training bank, or fresh holdout was loaded
or executed by this stage.

## The specific compatibility gap

Static inspection of the frozen learning implementation found two stock GRUs in
the generator. PyTorch's GRU keeps `_flat_weights` and `_flat_weight_refs` as
derived references to its registered parameters. The preceding strict adapter
correctly rejected unregistered tensor attributes, but that also excluded these
stock caches. This extension accepts exactly this validated derived structure.
It does not discard arbitrary tensor attributes or repair a bad cache.

The source-bound static mapping and conditional shape arithmetic are recorded in
`V6_KERNEL_STATIC_COMPATIBILITY_20261028.json` and its companion Markdown report,
whose identities are bound in `PREPARATION_REPORT.json`. That audit did not run
the scientific implementation. No complete candidate capacity bound follows
from the static parameter counts.

## Supported cache contract

`contract.py` accepts the exact stock `torch.nn.GRU` class, CPU float32 ordinary
contiguous parameters, one layer, biases enabled, batch-first inputs, zero
dropout, unidirectional operation, and zero projection size. Positive input and
hidden dimensions are checked; the actual execution tests use only 2 by 2 GRUs.

The four registered parameter names must have their stock order, shapes, storage
extent, and unique storage. `_flat_weights_names`, `_all_weights`,
`_flat_weights`, and `_flat_weight_refs` have exact container types and counts.
Each cached parameter must be the very same object as the corresponding
registered parameter. Each reference must be an ordinary callback-free weak
reference to that same object. Reordered entries, same-shape foreign parameters,
stale references, callable substitutes, storage aliases, and callbacks fail.

Every inspection rechecks the cache and stock method contract. The installed
`rnn.py` and `module.py` bytes are pinned. The selected method code, defaults,
closure, module namespace, and inherited method resolution are checked against
the pinned source, compiled without executing it. This includes GRU forward and
the methods that update and flatten its parameter cache, permute hidden state,
and check input/hidden shapes: eighteen selected methods in total. Instance and class
overrides fail before restore can write live state. Selected method code fields
are compared recursively with an explicit typed encoding; Python marshal's
reference and string-intern encodings are not treated as code identity.

The only omitted attributes are the two derived cache lists, after validation.
Their descriptor is included in the immutable structure identity. The names and
`_all_weights` remain in that identity. All other strict checks continue to
apply, including hooks, unsupported tensor attributes, model/reference storage
aliasing, immutable modes and context, SGD layouts, and RNG ownership. Trees
without a GRU call the old inspector directly. GRU subclasses do not receive the
exception.

## Explicit local seam

`GRUAdapter` inherits `__init__`, `capture`, `_mutable`, `_prepare`, `_apply`, and
`restore` as the exact original function objects. `_parts` and `_description`
are literal copies of their original complete function source, with equal ASTs.
`equivalence.py` checks both full source-byte hashes and AST hashes. It also
recursively inspects actual `LOAD_GLOBAL` operations, including nested code, and
checks every referenced binding. Only the local bindings named `model_parts`
and `module_identity` are replaced by the cache-aware inspectors. All other
bindings are the same objects as in the frozen adapter. There is no runtime code
rewrite, execution of compiled source, or global monkey patch in the adapter.

The detailed equivalence receipt is the `copy_equivalence` entry in each test
attempt. Tests intentionally and temporarily alter method dispatch to verify
rejection; they restore those methods and never change installed source files.
The trust boundary still includes the Python process and the remaining installed
Torch implementation. This is not a sandbox against arbitrary replacement of
PyTorch operators, global builtins, or native dispatcher internals.

## Verification and retained failures

Run from the repository root with the already installed runtime:

```sh
/workspace/scratch/e8a4dc33549f/runtime_v5/bin/python -I -B \
  experiments/multimodal_output_portfolio/field_bridge_v6_gru_adapter_preparation_20261028/tests.py \
  --report /workspace/scratch/e8a4dc33549f/new_gru_preparation_test_receipt.json
```

The report is created exclusively; an existing report is never overwritten. The
suite records attempts and successful operations. It does not import any
scientific experiment module beyond the two earlier state-preparation packages.

The successful writer run has nine tests. A 41,556-byte literal checkpoint is
written to a temporary file, restored into the same live GRU, and used for a
real next forward, backward, and SGD step. Input, output, returned hidden state,
loss, complete checkpoint state, and RNG state match exactly. Parameter cache
identities remain valid. None versus zero gradients, SGD groups and momentum,
bad cache/weak-reference layouts, dispatch overrides, hooks, storage sharing,
unsupported profiles, and non-GRU strict behavior are separately checked.

All earlier attempts remain in `evidence/`. The initial static fingerprint
attempt rejected stock methods because marshal byte encodings differed even
though all code fields were equal; it performed no model construction. Writer
test attempt 1 exposed two test-helper faults: a rejection fingerprint reused
the strict hook validator, and a mock teardown could not delete a function's
`__code__`. It performed zero forwards. The helpers were corrected without
changing adapter restore logic. Attempt 2 completed one tiny step, then rejected
the non-contiguous batch-first GRU output in the measurement helper. That helper
now explicitly copies this observed output to contiguous storage for comparison;
the state adapter's contiguous-tensor requirement is unchanged. Attempt 3 passed.
Independent review then demonstrated that an override of `permute_hidden` was
accepted by the initial thirteen-method inventory. That zero-forward counterexample
is retained separately. The inventory now includes all five remaining inherited
helpers called by GRU forward, and defaults are compared with explicit types to
reject equal-valued bool/int substitutions. Attempt 4 reruns eight inspection and
restore tests against the final sources with `--preflight-only`, including all
new method/default rejection cases; it passes with zero additional forward calls.
The earlier same-target replay and all source identities are retained, and the
independent review separately checks replay with the final method contract.
The retained writer attempts total three GRU forwards, three backward calls,
three SGD steps, and twelve explicit random draw calls. Constructor initialization
and isolated validation RNG instances are excluded from explicit draw counts.

## What remains outside this preparation

Restore is permitted only between steps with no pending autograd graph and no
concurrent writer. Successful copying advances tensor version counters. The
adapter cannot automatically find every external pending graph and does not
restore autograd internals. The prior stage's demonstrated version-counter
limitation remains. Returned GRU hidden state in these tests is compared as an
output; the initial hidden state is an explicit local input. A caller carrying
hidden state across branch boundaries must include it in a separate declared
state contract. This extension does not claim arbitrary recurrent-training
replay.

The real learning caller is not yet wired. It still needs the explicit immutable
context projection, separate training and inference action vocabularies,
baseline-continuation definition, kernel boundary integration, full prospective
registration, complete serialized shape and failure-retention bounds, and a
writer enforcing those bounds. The old ridge configuration and old scientific
protocol have not been edited. The existing candidate resource condition remains
at least 2 GiB of `f_bavail`, including for root; reserved free blocks are not a
substitute. A successful tiny GRU replay does not meet that resource condition,
establish a real-kernel replay, recover historical raw bytes, or close a scientific
gate. No raw evidence upload is performed by this stage.
