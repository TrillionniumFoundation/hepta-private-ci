# Bound real-report rejection through the native owner

This executable exercises the native scientific publication gate with the
completed V4 evaluation and **all 12 actual research parameter checkpoints**.
Its sole purpose is to verify rejection and preservation of an existing owner
snapshot. It never grants production authority or activates a candidate.

The driver is a standalone qualification workspace. It depends directly on the
actual repository's `codex-hepta-learning-artifacts` and `codex-hepta-types`
sources. Its JSON dependency and lockfile are confined to this executable; no
production crate dependencies are added.

## Evidence and trust boundaries

The exact protocol hash is compiled into the driver. Before opening an owner it
checks the report and both parameter payload hashes, all 12 task/head/seed bundle
identities, the research-only format and compatibility markers, the exact 264
policy probability-record identities, all 12 primary contrast identities, and
all four cost contrast identities. It verifies the canonical frozen candidate
and comparison definitions supplied by the exporter.

The driver independently aggregates the eight future-task upper bounds, four
old-task upper bounds and four measured CPU ratios, then checks agreement with
the exporter's adapter. It does not trust an exported `criterion_met` or
`all_registered_gates_met` flag to decide those numeric gates. Missing census
evidence or an invalid bound produces an unavailable native measurement.

Task and retention observations are the minimum number of distinct source
components among the required comparisons. CPU observations are the three paired
timed runs per task/head ratio. These units are different; seeds and heads are
never added to the source sample size. The negative task/retention lower endpoint
is a conservative mathematical support floor from float64 probability clipping,
**not** a lower bootstrap confidence endpoint. CPU upper/estimate is the maximum
measured ratio, **not** a confidence bound. The frozen cost scope includes each
controller's dense preparation, planning and actual execution; common encoder
and warmup costs are reported separately by the study.

The evaluator remains responsible for the per-comparison bootstrap statistics
and raw timing census. The exporter and independent replay audit remain
responsible for checkpoint tensors and the sealed execution inventory. This
driver binds their exact artifacts and checks the aggregates; it does not claim
to reproduce bootstrap draws or parse the float64 bundle into a serving model.

The executable creates a fresh, isolated owner under a new output directory,
imports the actual all-12 warmup predecessor as an opaque parameter artifact,
and constructs a candidate request for the actual all-12 `structured4_h8`
bundle. Both use the `research-numpy-float64-bundle.v1` compatibility identity.
The owner and reviewer keys are deliberately public ephemeral research fixture
identities in the source; they are unrelated to any deployed trust root.

If any actual numeric gate fails or is unavailable, those actual values are
signed and passed to `ScientificCandidatePublisherV1`. The result must be the
corresponding native gate rejection. Every owner file, the registry head, and
the absence of the candidate are then checked. The receipt archives the signed
canonical review bytes, reviewer public key, input/source hashes and owner file
hashes. These signatures establish local fixture integrity only.

If all numeric gates unexpectedly pass, this **negative-only executable** supplies
`Missing` review instead. The expected result is `MissingIndependentHostReview`.
It cannot turn an ephemeral qualification key into accepted independent host
review. Real publication would require an approved deployment policy, installed
reviewer trust and the ordinary owner lifecycle outside this driver.

## Run

Use a fully completed/sealed run and the exporter output. From the native
checkout, with Rust 1.95.0 installed:

```sh
cargo run --locked --manifest-path qualification/scientific-candidate-review/actual-review-driver/Cargo.toml -- \
  /absolute/path/cell_field_joint_protocol_v4.json \
  /absolute/path/evaluation.json \
  /absolute/path/gate-input.json \
  /absolute/path/predecessor-parameters.json \
  /absolute/path/candidate-parameters.json \
  /absolute/path/new-native-rejection-output
```

The output directory must not exist. The driver retains the isolated predecessor
owner and writes `native-rejection.json` beside it. Publication rejection is the
successful result of this qualification; the candidate remains unpublished.

The accompanying owner gate test qualification is separate: 102 actual-crate
tests passed, including synthetic positive publication/reopen/retry cases and
the gate failure matrix. This executable adds a real-data rejection receipt; it
does not convert those synthetic positive fixtures into scientific acceptance.
