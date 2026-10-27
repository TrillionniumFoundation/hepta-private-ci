# Structural and native development record

These are development experiments, not a sealed formal result. The development
seeds are **8011 and 8017**. Formal seeds 307, 311, 313, 317 and 331 were not used
to implement or tune this component. The repository parent commit
`57d2b9658839f11aa4685049f90cb7142d59026d` identifies the restored baseline; it
does **not** identify the changing, uncommitted v3 source executed during these
early development runs. No complete source snapshot was sealed before the early
runs. Their surviving artifacts and measurements remain useful diagnostics, but
they cannot be promoted into source-bound formal evidence after the fact.

## Preserved attempts

| Directory under `validation/` | Change and observed result | Evidence status |
| --- | --- | --- |
| `structure-dev-8011` | Raw and squared-energy clustering separated amplitude instead of local subspace identity. Both split proposals needed 4,856 bytes to satisfy domain floors under a 4,096-byte artifact budget. Both were rejected. Adaptive error stayed at the global single-cell error. | Unsealed development; failed proposals and their actual fitted artifacts remain retained. |
| `structure-dev-8011b` | Normalize squared energy within each row before clustering, preserving directional support while removing amplitude. A real split became useful; the two-stage convergent development flow passed the then-current priced comparison. | Unsealed development; old comparison had an accounting defect described below. |
| `structure-dev-8011c` | Reuse the global SVD already fitted and charged within the same write. Skip a two-to-one merge when that global fit already violates retention floors. This avoids paying for a duplicate full fit known to be infeasible. Seeds 8011 and 8017 showed the expected two-stage adaptation. | Unsealed development; matched-work padding was still mixed into the deployment-cost comparison. |
| `structure-dev-8011d-efficient` | Separate naturally costed fixed controllers from actual extra SVD repetitions used only as an equal-work causal control. Add audit-ledger metadata, common replay/schema/selection state, fixed owner bindings and migration reload checks. | Unsealed development; this is the final development accounting design, not formal qualification. |
| `structure-dev-final` | Also charge post-SVD reconstruction and every selection/trigger/split read multiplication. Repeat both development seeds with exact copies of the three executed structural source files and matching before/after hashes. | Source-bound development snapshot; it still uses development seeds and does not establish the formal gates. |
| `native-dev-8011` | Train an actual int16 Q12 memory cell, invoke the real native model port in two separate processes, recover the actual native runtime journal through an independent witness, and test six refusal cases. The 64 written-fact values and all logits matched Python; recall was 100%. | Native build was bound to its real source inventory, but this early run did not retain the canonical writer facts and executable alongside the result. |
| `native-dev-8011b-auditable` | Retain the canonical writer facts, audit query order, training receipt, exact executed binary and its source/build receipts. Reader processes still receive only the model, selected manifest and value-free Q12 query vectors. | Development bridge validation; formal execution must bind the frozen formal source commit. |

### Accounting defect corrected before formal execution

The initial structural study returned only the fixed controller's ledger after
padding its work with real repeated SVD fits. Using that padded cost as the sole
deployment baseline could make adaptive maintenance appear cheap by forcing the
fixed alternative to waste computation. This was a real comparison defect.

The final study records the fixed controller's natural artifact, error, fitting
work, time and retained bytes **before** work padding. It also executes and
records the padded control. A strict flow pass requires at least 5% hidden MSE
improvement and lower priced loss against **both** the most accurate naturally
costed fixed controller and the matched-work fixed controller. Both fixed
choices use whole-flow selection outcomes, never hidden outcomes. The two
prices remain 0.02 for training work and 0.02 for retained state. They were not
lowered to recover a pass.

With corrected accounting, the two development convergent flows improved hidden
MSE by approximately 96.22% and 98.25% against the naturally costed fixed choice;
priced-loss differences were approximately -0.09590 and -0.13622. These are
development observations from `structure-dev-8011d-efficient`. The final
source-bound development replay, with additional reconstruction/selection work
charged, retained the same MSE gains; priced differences were approximately
-0.09892 and -0.13921. Static heterogeneous flows were close to a strong
fixed four-cell controller; the all-flow strict gate remained false. Stable and
random controls also retain their separate error regrets and costs. Their
strict failures are not reclassified as passes.

## Final declared controller

The written source is a numeric matrix. Query addresses are stable row and
column identifiers, and all facts are available to the writer. Selection
addresses are separate from hidden read addresses; no hidden query set is
passed to the structural owner. This is memory of written facts, not forecasting
unknown future values.

- The maximum serving factor artifact is 4,096 bytes, including int16 record
  factors and decoders, int32 centers, route bits, availability bits and headers.
  A fixed 80-byte source/generation/artifact owner binding is charged to every
  arm. Shared raw replay, source schema and selection addresses remain additional
  maintenance state and are reported for every arm. They are not called free
  compression.
- Begin with the maximum global SVD rank allowed by the artifact budget. On a
  later write, freshly fit the previous partition as well. All fitting uses the
  current valid written values; source exclusion and live revocation admission
  belong to the separate lifecycle owner.
- Skip split search at selection MSE at or below 0.25 or at four cells. Otherwise
  estimate the leading residual-energy ratio with eight power iterations. The
  trigger threshold is `max(0.15, 4 / columns)`. Random controls pay for this
  diagnostic even when no candidate is trained.
- At most two split rounds each propose raw-vector and row-normalized
  squared-energy bisections, with at most 12 clustering iterations. Real full
  SVD fits produce the candidate subspaces. Selection-coordinate rank curves
  allocate the serialized rank budget. Each proposed partition/domain has a
  minimum rank satisfying the incumbent/initial domain MSE floor: the smaller
  domain error times 1.02, plus 0.25 MSE units. An unfunded floor rejects the
  candidate; its work and forensic artifact remain charged.
- A split needs at least 5% selection MSE improvement. An eligible merge or
  whole-bank consolidation must satisfy the floors and reduce serialized size
  by at least 10%, or (for consolidation) improve selection MSE by at least 5%.
  A reused basis must already have been fitted, source-bound and charged in the
  same owner invocation. No inherited or concatenated tensor is called a fresh
  fit.
- Fixed controls have one, two or four cells. Their cell count stays fixed, but
  they may relearn raw/energy routing and selection-based rank allocation at
  every write. The best fixed count is selected in hindsight over the entire
  selection flow, giving this comparator more information than the online
  adaptive owner. Natural cost and equal-or-greater optimization work are both
  visible.
- Every unique full fitted basis and selected artifact is retained by digest.
  Real SVD calls, `rows * columns * min(rows, columns)` work, post-SVD
  reconstruction products, explicit selection/diagnostic multiply work, fit
  and owner wall time, peak temporary factor bytes, retained audit
  metadata and common replay are reported. These proxies are not measured
  hardware FLOPs or currency. Read-work horizons remain 1, 10 and 100 batches.
- Selected artifacts are actually reloaded and their hidden coordinate reads
  compared before reporting migration parity. The address identity stays stable
  while serialized row routes and local row offsets migrate together.

The flow set is static heterogeneous subspaces, heterogeneous-to-shared-subspace
convergence, stable low rank, and random values. The convergent-specific gate is
an explicitly narrower capability result. It cannot replace the all-flow gate,
the original static heterogeneous expectation, or the preserved v2 result of
only two strict structural wins in five trials.

## Native qualification boundary

`memory_model.rs` implements the real integer `NeuronModelPort`, with strict
artifact length, dimensions, digest, selected manifest and generation bindings.
The example composes it with the real `NeuronRuntime`, `SparseJournal` and
`FileAnchorWitnessStore`; it does not substitute fake model outputs or a mock
journal. A durable host selection binding prevents recovery with a different
source/manifest/runtime tuple. An inactive calibration window intentionally
keeps every native signal in abstention and never grants authority.

The extractor links the real three crates' source directories, copies their
original manifests, keeps only exact versions/checksums from the repository
lock and records every source hash. The original nextest configuration is kept
as `nextest.source.toml`; only package-specific overrides for packages absent
from the extracted workspace are omitted from the active copy. Default/local
timeouts and retries and relevant generic overrides remain unchanged. The
original repository configuration, CI and lock are not edited.

The first native run used the repository's `just test` entry point: 90 Neuron
tests passed, zero skipped, including four new backend tests. Native bridge
cases separately test tensor tampering, generation drift, source-selection
drift, out-of-range input, answer-bearing query schema rejection and rollback of
an acknowledged journal while the witness remains current. This is exact-lock
three-crate qualification, not full-workspace integration, production model
admission, an authenticated trainer, or live source-revocation freshness.

Before formal native execution, regenerate the extracted source inventory and
build receipt using `prepare_native_workspace.py --build-example`. The study
checks source, manifest, lock, test-policy and binary identities before and after
execution and retains the executed binary. Formal runs reject a build whose
checkout commit differs from the declared source commit.
