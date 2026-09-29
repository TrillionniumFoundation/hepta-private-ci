# Bounded Cell scorer training

This implementation stays in the existing `learning.operator` owner. It is an
experimental numerical component, not a model service, database, artifact
selector, additional learning architecture or production training ingress.
The authoritative design remains `docs/learning/NEURAL_BIOMIMICRY_SPEC.md` and
`docs/learning/NDU_FBSDE_SPEC.md`; the existing native ledger, authenticated
training boundary, signed evaluator and artifact owners retain their authority.

## Implemented profile

`cell_head.py` fits a **private copy** of the pinned Laya scoring head
(LayerNorm / Linear / GELU / Linear), using frozen question-conditioned marker
features and fixed exogenous soft labels. The encoder, decision transformer,
type embedding, selected scorer, temperature and hard objective do not change.
This is supervised prediction fitting, not an NDU actor, a general FBSDE solver,
organ credit assignment or evidence of multiscale improvement.

The numeric profile is CPU float32, eval-mode layers, deterministic canonical row
order and SGD without momentum or hidden RNG seeding. Complete ordered options,
features, targets, row/group/outcome/source identity, scope, objective and base
bundle bind the dataset. Duplicate outcomes cannot increase the support count.
Separate group names are not proof of separate real observations or principals.
The learning owner must resolve and authenticate those identities and current
withdrawals; a Python digest or dataclass cannot do that work.

Training checks the original time horizon around bounded steps, clips gradients,
and projects the aggregate parameter delta into a declared L2 ball. A conservative
owned-tensor allocation calculation is checked before candidate copies; it is not
an OS/device memory attestation and excludes the independently charged encoder.
No data or insufficient groups returns no change without updates. A zero-delta
fit also returns no change while retaining consumed steps and time. Expiry or
invalid data never modifies selected parameters or makes consumed work free.

The candidate is bounded `safetensors` data, not executable/pickled code.
`restore_candidate` verifies exact base/scope/objective and semantic/payload
identities, and returns another private head. It never mutates the running
selected model. Compatibility is not admission: authenticated artifact lineage,
current-source use, anti-rollback, withdrawal, signed selection and a real host
consumer remain required before any product adoption.

## Borrowed storage and the actual training snapshot

A frozen `HeadRow` does not make its Tensor storage immutable. After the existing
copy-budget check, fitting clones complete rows and the selected head, then
validates the dataset and base digests on those actual private copies before any
optimizer step. Checking only the caller's storage before and after fitting would
miss a change/copy/restore (ABA): the returned identity could describe different
features, labels, parameters or normalization than the bytes actually trained.
The final caller-drift checks remain. Ordinary unchanged inputs retain the same
numerical algorithm, row order and candidate identity; no-data still allocates no
candidate. A transient change after snapshotting cannot influence private inputs.

`test_cell_snapshot.py` deterministically reproduces these allocation-boundary
races with real small CPU tensors and controlled owner callbacks. It also checks
no-data/no-update, budget rejection before copies, retained drift rejection and
unchanged-candidate parity. This is snapshot integrity, not authenticated source
permission, independent outcomes, a process sandbox or longitudinal improvement.

## Execution profile and tensor identity

The scorer profile admits only the exact eager CPU layer types, tensor shapes
and independent parameter storage. Active module/global/autograd callbacks,
instance execution or serialization overrides and compiled call substitutions
reject before admitted model work. Actual candidate copies are rechecked before
updates and restoration. Tensor digests alone cannot describe these Python
execution changes; accepting them would mislabel the fitted behavior and can
change the effective update when storage is tied. Supported unmodified scorers
retain their existing schema, digest and numerical algorithm.

`test_cell_profile.py` covers hooks, overridden calls, shared storage, candidate
copy boundaries and unchanged behavior after hook removal. This is a compatibility
profile inside a trusted exclusive-owner process, not an isolation mechanism
against arbitrary Python execution, class monkey-patching or concurrent foreign
mutation. Source authentication, independent outcome evaluation, artifact
selection and actual process isolation remain with their existing owners.

## Actual model experiment versus fixtures

The existing `Hepta Laya real-model smoke` workflow checks source-head and fixed
base-merge trees on Linux/macOS. It reuses the existing pinned model preparation
and offline inference driver, then runs `laya_training_smoke.py` on that exact
prepared bundle. There is no new dependency download or mutable model selection.

The harness has exclusive ownership of an isolated qualification model. Temporary
read-only hooks capture the **actual scorer inputs** through the existing driver;
the baseline head plus checkpoint-selected option-count temperature must match
the SDK's rounded predictions. Hooks are removed on every exit. This is not a
safe concurrent hook API for an active product model. The actual CPU/eager/
float32 profile is checked; no mixed-precision fallback is silently accepted.

Eight synthetic training cases are encoded before fitting. Four different future
and four retention cases are encoded only after the candidate is frozen. The
labels and logical time indices are predefined fixtures, not real-time outcomes,
independent evaluation principals or a consumed final holdout. The separate
`learning.eval` numeric leaf computes paired accuracy, Brier and log loss with
identical denominators and equal declared-group weights. It has no trainer,
threshold policy, holdout writer or promotion decision. Improvements AND failures
are retained; CI asserts execution/identity mechanics, not invented efficacy.

`training-report.json` binds real model-forward count, actual SDK input tokens,
feature/receipt identities, exact tested source, private update, all paired
metrics and measured phase times. Loading, feature preparation, fitting, restoring,
evaluation and persistence share one bounded overall horizon. The record keeps
memory attestation, production composition, artifact adoption, final holdout,
NDU efficacy and structural-plasticity claims false. Existing native signed
metric/holdout owners must consume real authenticated outcomes for those claims.

Run the numerical and fault tests locally:

```sh
python3 -m unittest discover -v -s codex-rs/hepta-bellman-operator/python -p 'test_*.py'
python3 -m unittest discover -v -s codex-rs/hepta-intelligence-eval/python -p 'test_*.py'
```

These tests use real PyTorch operations on tiny synthetic tensors. They are not
real Laya weight evidence. A real-model claim requires the separately retained
workflow `training-report.json` and matching `candidate-head.safetensors` digest.
The artifact is experiment evidence, never an automatically selected runtime file.
