# Copy and load the actual affine-price dependencies

This change repairs the `copy_reference` conversion and recursive `load_state_dict`
path in `affine_ports.py`. It is based on exact commit
`b3fdc981568ab9ce122d2fb569372651e0b4b314`.

## The defect and the narrow contract

The old constructor caches prices using a default `Published()` law and its
default grid before `copy_reference` loads the reference tensors. Python `Law`
fields and the derived Python constants are not present in `state_dict`.
Loading a nondefault grid therefore leaves the old cache; loading the tensors of
a different law also leaves the default Python constants. Matching tensor keys
does not establish matching functions.

The converter now deep-copies the complete reference `prices` object before the
final state load. The affine module owns a load-state post-hook, so all its child
buffers have been loaded before it rebuilds `price_center` and
`price_relative_slope`. The hook also runs when a containing parent module loads
its state. Existing persistent cache keys are retained for compatibility, but
loaded cache values are always recomputed from the current dependencies.

Bare `state_dict` still cannot supply a missing Python law. Direct state imports
are qualified only for the same installed law/profile. A different law requires
`copy_reference` with the complete coherent reference object. This patch does
not detect arbitrary `.data` writes, concurrent mutations, dynamic law assignment,
or conversion of the cache to another dtype/device after construction. After
coherently installing such dependencies, explicitly call `rebuild_price_cache`
or reject the edit. Editing `Law.p` alone does not reconstruct all `Published`
constants. Learning physical-law buffers through gradients, TorchScript and
`torch.compile` are outside this contract.

The original equations, the price gate, benchmark results and quality selection
rules are unchanged. This is not a claim that the original default-profile
benchmark was numerically wrong, nor that repairing a cache improves task quality.

## Six fixed synthetic controls

1. The default profile agrees with the literal reference for both old and repaired
   implementations.
2. A complete nondefault `Published(Law(...))` is copied without object or storage
   aliasing. The repaired pricing function agrees with the actual reference;
   the exact old implementation is required to disagree.
3. A nonuniform grid has matching cuts and reset interpolation. The same repaired
   and old controls are applied; no inconsistent reference is called a physical
   qualification.
4. A parent recursively loads same-law, nondefault-grid child state. This exercises
   the registered child post-hook, not a manually invoked rebuilding helper.
5. An affine state with intentionally poisoned, same-key cache tensors is loaded.
   The derived buffers must be rebuilt instead of trusted.
6. A deep-copied affine owner loads a different coherent grid. Its hook must use
   its own loaded state without changing the original owner.

The exact old affine module is preserved as `affine_cache_fixture_b3fd.py`; its
SHA-256 is `9df6ea77123b1f8f4c747294a0e01addc6938617ff1da009eecc9ac6947e28de`.
The original `population.py` and `he_xiong.py` remain unchanged. Fixed principal
ratios, complete law, five grid atoms and tolerances are in the protocol before
execution. No FordA, catalog, checkpoint, labels or task selections are accessed.

## Real cost and execution status

**Prepared, not numerically executed.** The local preparation used only AST,
source, identity and protocol inspection. Local Torch is unavailable and was not
installed. Qualification is proposed in the separately pinned CPU runtime
Python 3.12.3 / Torch 2.10.0+cpu; this is not a bitwise qualification of the author's
Torch 2.8 environment.

The complete attempt is limited to one CPU, 1 GiB memory, zero swap, 64 tasks,
20 worker CPU seconds and 40 wall seconds with at most five seconds for cleanup.
It creates nine population objects via constructors and two via deepcopy.
Ten `Published` constructions call `autograd.grad` twenty times to form their
existing analytic derivative buffers. Those operations are counted and timed;
this is **not zero gradient computation**. Four literal and ten affine explicit
pricing calls, plus twelve literal calls used to build caches, return 1,200 price
values. There are ten top-level state-load calls and nine repaired cache rebuilds.

There are zero full population/network rollouts, task-loss backward calls,
optimizer steps, task-data rows or selected task candidates. These zero counts
do not erase the explicitly counted pricing evaluations or constructor autograd.
Dependency installation, environment setup and failed attempts remain separate
costs and are retained with the output. No training-speedup claim is made.

The launcher creates its output and `LAUNCH_ONCE.json` exclusively, starts one
owned process group, preserves started/returned counters and retains partial
progress on failure. Missing or malformed completion evidence remains unknown.
There is no automatic retry. The new workflow accepts one exact research-branch
push with `run_number == 1` and `run_attempt == 1`; root remains the sole publisher
and executor. Inherited workflow triggers must be reviewed before that push.
