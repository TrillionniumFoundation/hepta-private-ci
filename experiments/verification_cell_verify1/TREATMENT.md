# Actual checker and host-treatment records

Create `TreatmentJournal.create(shadow, checkers)` before any shadow events.
Record a risk prediction before `choose(...)`. Its exact prediction, frozen model
and checker identities, and actual completed observation history bind the choice.
The scheduler digest is a host-declared identity, not executable attestation.

Call `start(choice["record_sha256"], original_operation_id)` before the host invokes
the selected checker. The journal records intent; it executes and authorizes no
effect. Pending calls stay pending across recovery. Never interpret absent replies
as permission to repeat the checker with the same or a different operation ID.
`complete(...)` admits the original pass/fail/observed-unknown reply, evidence digest
and exactly three cost fields: wall_seconds, cpu_seconds, energy_joules. Values
are finite nonnegative numbers at most 1e12, or null when unknown.

Late original replies can reconcile after completion without changing the host
disposition or terminal label. `record_disposition(...)` precedes `shadow.finish`;
acceptance requires a literal true host gate and no pending checks. Permission,
schema and original-owner validation remain mandatory host responsibilities.
This unchanged-artifact stage refuses repair actions; a changed candidate needs a
separate subject and executed-policy terminal target.

`report()` joins the full frozen roster in one transaction, including omitted
predictions/choices/treatments, pending calls and missing labels. It preserves
both false-acceptance denominators, acceptance coverage and partial measured costs.
Checker costs exclude prediction, scheduling, label collection, recovery and
historical work. Full physical cost remains unqualified. Adaptive partial checker
histories are not complete paired calibration panels.

Externally retain manifest, registry, base ledger and treatment ledger roots.
Recovery accepts a base `expected_ledger_sha256` in `ShadowJournal`, and a separate
treatment `expected_ledger_sha256` in `TreatmentJournal`. These pins compare exact
current checkpoints; reconcile newer heads read-only before updating a pin. They
do not authenticate clocks, physical execution, gate evidence or independent
label custody. Label callback attestations remain unretained.

Local subprocess fixtures establish engineering behavior. Actual error reduction,
acceptable coverage and complete-cost net utility still require frozen prospective
real-task controls. Scientific admission HOLD; production authority NONE.
