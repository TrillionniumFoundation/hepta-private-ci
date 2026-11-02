# Compiled DP deployment reference

`compile_policy(public, law, confusion, reference_scope=..., cold_law=True)`
builds a bounded table for the supplied finite CTMC and decoder model. Compiler
inputs are public schedules/prior plus explicit model parameters. It accepts no
world folder, evaluator, packet content, latent path or future observation. Q is
the future net reward from the current state; sunk fees do not change the best
action. Keys include tick, remaining budget, broken/pending status and the full
completed-observation history, including request and observation times.

Always use an accurate scope label. Formal references should distinguish
`nominal_law_train_decoder` from `known_environment_law_train_decoder`. The latter
knows environment generator parameters; its decoder law is still TRAIN-fitted.
Neither is guaranteed optimal for an unknown true decoder or a different law.
The fixture uses an explicitly declared confusion matrix, not fitted evidence.

Each public world gets a **new Oracle and new history/Q caches**. `cold_law=True`
also creates a new law so previous teacher/data-generation transition caches are
not silently borrowed. `cold_law=False` permits reuse of a public physical
transition bank: it depends only on supplied raw parameters, dt and exogenous
drive. That preparation, memory and serialization must be recorded once, with
standalone/amortized allocation declared; it is not free teacher computation.
Both modes have identical table values. A table covers all structurally legal
histories, including counterfactual missing outcomes at failure probability zero.
Unknown states raise; execution has no dynamic Oracle fallback.

```python
artifact = compile_policy(public, law, train_confusion,
                          reference_scope="nominal_law_train_decoder")
policy, payload, load_cost = serialize_load(artifact)
episode = run_episode(public, world_folder, adapter, policy, controller="value")
```

`CompiledPolicy.predict(public, state)` returns six Q values (illegal coordinates
are zero and must be masked) and the deadline-six belief. Fixed/value share the
same table and belief. `run_episode` uses the actual task Owner; it reads the
evaluator only after termination. Each decision contains its Owner receipt and
lookup/controller CPU/wall. Compile, serialization and load are separate measured
phases; actual content reads/FullHX/fees are in Owner receipts. The complete
reference process must also be timed externally, including imports, law/setup,
all compiles, files, execution, report/export and exit. Do not charge compilation
to a hidden free shared cache or attribute it to learner inference.

`serialize_load` reports serialized bytes and reachable Python object sizes.
The latter excludes allocator/RSS peak, and the measurement traversal itself is
outside its load timer. Complete process timing includes such diagnostic work;
it cannot by itself establish a deployment latency or throughput advantage.
Public-matrix precomputation is allowed in a strong deployment comparison if its
cost and lifecycle are explicit. This implementation is a strong compiled finite
model reference, not a claim that every possible DP implementation is slower.

Fixture qualification is in `evidence/joint_compiled_dp_fixture_final`: three
failure settings (0, .15, 1), 440 table states each, 1,320 comparisons against a
separate Oracle instance, maximum Q/belief discrepancy 5.55e-17. Compile is
checked with private Path reads blocked; cold/public-physics-warm tables agree.
Actual Owner runs cover 13 due-read attempts and ten successful FullHX decodes,
including a missing packet even in the counterfactual zero-failure fixture.
Cold compile CPU is 0.036–0.070 s per fixture; tables are approximately 87 KB
serialized and 311 KB as reachable Python objects. The complete fixture worker
uses 0.861445 CPU s, including imports, all compiles, independent verification,
actual reads, serialization and exit. These are correctness/instrumentation
fixtures, not trained-model efficacy, formal confirmation or speedup results.

Run from the repository root with one BLAS thread and a new directory:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.digital_joint_20261102.joint_compiled_dp_validate --out /tmp/new-compiled-dp-fixture
```
