# Generation state and the neuron feature boundary

`GenerationDriver` implements the existing `NeuronFeatureDriver` port through
`generation_driver::neuron`. The driver executes the registered Python model;
`InferenceWorker::run_neuron_features_receipt` builds the existing typed receipt.
`InferenceControlModelPort` verifies that receipt before exposing a model output.
No executor, authority source, policy selector or daemon activation is added.

## State and request identity

The registered profile accepts hidden width 96. Every generation state preserves
384 float32 bit patterns in the order `h, image, text, context`, its full backend
state hash, plan index and snapshot-bound state hash. All four blocks contribute
to a bounded feature:

`p[i] = tanh((((h[i] + image[i]) + text[i]) + context[i]) / 4)`.

Each float32 value expands to float64 before the ordered sum. Multiplication by
2^24 and rounding halfway away from zero produce the Q24 representation. Raw
inputs must be finite and within [-8, 8]; this transformation never clips invalid
input. The feature width, transformation and numeric convention have a stable
profile digest shared with the Python calibration implementation.

Prediction is `p(previous actual state)` and drive is `p(current actual state)`.
The native sparse kernel measures their maximum absolute component difference.
This persistence residual is not inherently semantic confidence or an OOD score.

An immutable host registration binds the complete raw generation request, all
checkpoint/model/source pins, complete predecessor state, feature request and
its pre-existing worker authorization. The tick identifier includes the raw
request digest. The feature input digest binds the complete tick context, while
the separate feature-vector digest retains its existing numerical meaning.
The driver compares the fresh execution's complete predecessor to registration;
agreement of only the lossy 96-value projection is insufficient.

Requests cannot select an executable, module, checkpoint or arbitrary artifact
path. Registration remains bounded to 128 requests and eight actions per raw
request. Both token limits must reserve eight positions before executing or
returning a cached result. Exact feature retries retain the original measured
receipt; another context cannot consume that execution as a fresh observation.

## Cost observations

The evidence keeps these distinct measurements:

- Full child-process wall time, including Python startup, model loading and the
  actual generation transitions and output.
- The bounded projection's wall time.
- Driver entry through the produced observation, including registration checks.
- The child's measured peak resident memory.

The current V1 feature receipt has a numeric `transient_allocation_bytes` slot.
This cold-process profile explicitly binds a **transient child resident-byte
charge** to that slot. It does not measure allocator peak live bytes or cumulative
allocation. RSS is not claimed to bound virtual or cumulative allocations.
The resource-profile digest is included in the head identity and retained
separately in feature evidence. This adapter therefore does not establish the
specification's target-host allocator qualification. Missing failed-process
memory remains `None` in the retained evidence; a legacy numeric zero on a
failed receipt is not a measured zero.

The native admission experiment retains the prescribed 3 ms / 8 ms latency and
512 KiB resource envelope. It does not reinterpret a fast projection as the cost
of the preceding model execution, or relax the envelope for cold Python startup.

## Frozen calibration and observed failure

The pilot specification has SHA256
`7472ac00a31a032d164101eb9e691622bdf3b52d5400b9f4ca525a32396c3e49`.
It selects the first registered seed (17), the completed full-002
`terminal_entropic_ndu` checkpoint and frozen Reward A. It uses validation pairs
640..703 and 704..767, with one observation/action/label per independent pair.
Source IDs and original pixel hashes are disjoint from forecast and competence
partitions. Audit B and formal rollout quality do not select the profile.

Each cohort has 32 ordinary observations and 32 predeclared observations with
all visual pixels/masks absent and both digit hints unknown. Keep/swap remains
visible. This tests only that constructed absence mechanism. Semantic errors
are not relabeled as OOD. ECE uses ten fixed bins against joint output success
measured from original UTF-8 and reopened PNG bytes by Reward A. OOD false
acceptance uses the 32 predeclared OOD observations as its denominator.

The one frozen pilot measured ECE 503,354 ppm and 612,707 ppm. Both cohorts
accepted 32/32 OOD observations: false acceptance 1,000,000 ppm. Native profile
values are the maximum across the two prespecified cohorts. The immutable gates
remain ECE <=30,000 ppm and false acceptance <=4,999 ppm. Raw outputs, complete
states, projections, labels, count audits and the actual executed Python source
are retained. This is a measured **NO-GO**, not an unfinished calibration gate.

`v6/verify_neuron_calibration.py` independently recomputes the recorded rows,
full state digests, raw output hashes and aggregate mathematics without fitting
or model execution. It can create the explicit native fixture for fixed pair704.
`hepta-agentd/tests/generation_neuron_calibration.rs` exercises the real
submit/reserve/assign/feature-execute/settle path and requires
`NeuronRuntime::bootstrap` to return `InvalidCalibration` with no checkpoint
commit. It uses explicit local test authority and a separately retained witness.
Its NDU context digest explicitly means **test-only, no NDU valuation owner**;
it is neither a model checkpoint identity nor online NDU integration evidence.

Because registration fails, an admitted `AgentdNeuronOwner::tick`, qualified
intuition use, production daemon activation and learned confidence/OOD quality
remain unestablished. The integration test must not replace these measurements
with illustrative passing constants.
