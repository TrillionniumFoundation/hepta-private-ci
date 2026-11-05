# Actual image/text to explanation/diagram execution

This fourth review stage composes the pinned pretrained backends with a public
decision interface and complete captured action attempts. It is a development
execution canary. A learned Hepta controller, new four-arm generator training,
independent semantic acceptance and production qualification remain open.

Two schedules are fixed before model execution, on one public source at seed 17:

- Direct: perceive, text, draft, verify, STOP.
- Revision: perceive, text, draft, verify, revise, text, refine, verify, STOP.

These exercise every requested action but are not an efficacy comparison.
Both use the same image and are not independent task samples. The exact online
DP from stage one is a separate finite reference; it is not quietly supplied
with counterfactual neural-generator results.

Controllers see only immutable public observations, existing candidates,
plan version, critique, action history and remaining resources. References,
future random tables and evaluation scores are absent. Python interface
separation is not an adversarial operating-system isolation boundary.

Changing the common plan invalidates the old selected text/image pair; old
files and their costs remain. Refinement may explicitly consume an old draft
and produces new bytes bound to the current plan. STOP requires the current
pair and rechecks their hashes. Initial STOP is legal abstention and loads no
generator. An exhausted horizon cannot silently deliver. Output is buffered
until the final result; irreversible streaming delivery remains a later stage.

Each action, controller invocation and finalization has an exclusive CPU/wall
interval. Failed/partial artifacts, cancellations, provider timeouts and deadline
overruns remain in the ledger. Timeouts are checked after synchronous calls and
finalization; this is not preemptive cancellation or a physical hard-deadline
guarantee. Inclusive outer run envelopes cover report construction/writes and
must not be added again to nested action totals. Acquisition, environment,
training, independent evaluation and unknown energy are separately identified.
No tariff or NDU benefit is manufactured from raw resource measurements.

The VLM critique is a public consistency observation from the generation
family. It is explicitly not an independent semantic score. Images existing
on disk do not establish correctness, utility or cross-modal consistency.

## Reproduce

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.acquire_models --root /tmp/dual-models
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.run_real --models /tmp/dual-models --output /tmp/dual-evidence --source-sha EXACT_COMMIT_SHA
```

The dedicated `ndu-decision-audit.yml` workflow checks its actual source SHA,
runs the exact, ledger, model-boundary and real-file contracts, acquires fixed
weights, executes both schedules, and retains errors and outputs even on a
failed job. Model weights are excluded from uploaded artifacts. A separate
run receipt is required before reporting actual neural execution.

Remaining evidence for the proposed training paradigm: source-separated real
tasks, validated independent evaluators, validation-tuned fixed schedules,
one-step VOI, lightweight and finite-horizon controls, equal-budget four-arm
training, joint-versus-separately-trained composition, future windows, and
full costs. Audio/video timing, cross-frame identity, long memory and
irreversible delivery cannot be inferred from this buffered dual-modality test.
