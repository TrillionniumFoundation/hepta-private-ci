# Opaque teacher observation: prospective profile stage

Base: capture #7245, fe65dd25d152d8ea3b5c581a8a6fd3412442ca00.
The retained SDK turn is an unsigned typed projection, not raw wire provenance,
teacher execution, a verified teacher checkpoint, HumanTrain consent or a label.

This stage adds a separate strict record profile. Existing data.py remains
byte-identical, preserving its V1 schema and semantic-verifier source digest.
The teacher's model/weights and generation receipt remain explicitly null.
Teacher trajectory entries remain actor=teacher, kind=observation,
executed=false and masked. Provider/model labels cannot substitute for weights.

The profile binds the original capture byte SHA, explicit ordered user/agent
item IDs and full item projections, exact single-text task input, reported phase
(including unknown phase), and the separately supplied original student policy
commitment. This policy is not automatically equal to native Decision.policy_digest.
No claims about a complete hidden trajectory or teacher authenticity are made.
Integer-only bounded records retain the native canonical-identity subprofile.

The local json_artifact callback can produce an explicitly unsigned semantic
receipt with both implementation hashes. It cannot create a native Evaluator
signature, signed Decision/Outcome, dataset permission or production admission.
Caller authorization declarations are preserved verbatim; capture grants none.

Seven authored controls cover exact source binding, unknown weights/no consent,
identity/actor promotion rejection, prompt and item identity/order, local semantic
receipts, numeric/target refusal and full source reconstruction. After actual
repository Python formatting, freeze the exact two sources and execute this
seven-test module once with a 30-second cap. No SDK/teacher request, optimizer,
model fit, Cargo command or existing E1-E6 experiment is in this gate.

Follow-on slices must connect this profile to the actual paired derive/encoding
consumer and then the original owned native material consumer. Core/AuthBus,
original HumanTrain, frozen raw/canonical pins, original two signed native event
pairs and the real late Evaluator signature remain mandatory. Merely accepting
this schema does not close those downstream qualifications.
