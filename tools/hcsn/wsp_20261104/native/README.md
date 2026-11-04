# Actual-checkpoint qualification of the native Rust operations

These drivers execute the shipped HeptaRuntime MCP binary. They do not mock
the planner, artifact publisher, forward operator or recovery. Both freeze an
executable copy in a new private work directory and verify its identity before
and after execution, so replacing the build output cannot change the recorded
binary identity.

The retained binary SHA-256 is
`61170e9ba6c6cd17d907f11e2c3e3b01e59d3855ca3ab11de26205c8ba996228`.
The companion runtime qualification binds its source base and edited sources.
Compilation and these experiments were performed in an isolated checkout;
no active service or trading model was replaced.

## Public Hepta fixture

The fixture in `../joint/fixtures/rust_fixture.json` comes from the already
public, hash-pinned Hepta joint model. It contains 64 original TRAIN rows, 49
features including an explicit constant, three weighted continuation targets,
and the original head. This is a numerical test, not independent holdout data.

Use an existing Python environment with NumPy and safetensors, and a newly built
runtime from the qualified companion commit:

```sh
python run_hepta_native.py \
  --binary /absolute/path/to/hepta-runtime \
  --fixture ../joint/fixtures/rust_fixture.json \
  --work-dir /absolute/path/to/new-private-hepta-run \
  --output /absolute/path/to/new-hepta-summary.json
```

The driver calls the F64 ridge planner and compares its solution with independent
NumPy linear solves. It applies the resulting 147 F32 edits to the first three
rows of the actual 4×49 head. The 49 Belief values remain byte-identical. A
separate request forces a preservation-constraint conflict to exercise rejection
and exact reverse publication. This artificial conflict is not presented as a
naturally occurring model defect.

Retained results in `native-hepta-summary.json`:

- Maximum F64 parameter difference: `9.766493169749424e-16`.
- All 147 proposed F32 elements changed; the Belief row and source file stayed
  unchanged.
- The candidate was accepted on the supplied TRAIN rows. The guard's unweighted
  four-output MSE is deliberately distinguished from the planner's weighted,
  proximal per-head objective.
- The forced conflict was rejected and all restored bytes matched the parent.
- Planner time was `.00778185` seconds; full driver time was `12.174740699` seconds.

## Private Current100k fixture

The required fixture is not published. An independently authorized reviewer must
obtain the exact file identified by
`../pocket4/private_input_manifest.json`. The SHA-256 is
`205bb2d9d1329c5a4ee134ce12146c29e842da80a8662a8e3533e0b85a4bd90a`.
No private feature rows, labels or weight files belong in this public directory.

```sh
python run_current100k_native.py \
  --binary /absolute/path/to/hepta-runtime \
  --fixture /absolute/path/to/authorized-private-fixture.safetensors \
  --work-dir /absolute/path/to/new-private-current100k-run \
  --output /absolute/path/to/new-current100k-summary.json
```

The driver lowers the historical F64 affine model and arrays to F32 and appends
a constant feature, producing a 1×769 tensor. It verifies the exact rational
squared norm of the rounded USD head against `10.0001` before publication.
The native guard does not itself enforce this norm constraint.
The candidate heads were already solved and frozen in the independent fixture.
This driver does not call the native ridge planner: 769 features exceed that
planner's 64-feature limit. Native planning is qualified by the separate public
49-feature Hepta experiment above.

The 18→next18 and 36→next18 candidates worsened RMSE. Both were rejected and
recovered with exact full-byte equality. The 54→same54 resubstitution candidate
passed only `accepted_on_supplied_rows`; that outcome is not independent efficacy.
Every input row had already been exposed in earlier research. The retained
aggregate is `native-current100k-summary.json`; full private receipts and
temporary models remain in the private work directory.

## Interpretation and accounting

F64 and F32 results have separate identities and errors. These experiments do
not establish bitwise equivalence with the original F64 models, fresh task
utility, full CTMC execution, prospective trading returns or live-model rollback.
The original files are never overwritten. Recovery creates and verifies another
isolated artifact.

Driver time includes process setup and protocol interaction; native operation
time includes the scoped operation. Neither includes original training, feature
or teacher construction, LLM usage, compilation, source transfer or energy.
The retained receipts explicitly mark production eligibility and independent
holdout verification false. Any rerun must use new output paths and retain its
own timing, binary identity and result, rather than overwrite this evidence.
