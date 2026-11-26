# V5 retained evidence bridge

This module connects the actual peer candidate to its retained trial, edit,
cold-load, task, profile, population, protocol and peer receipts. Its complete
input is 14 fixed files totaling 78,530 bytes. It imports only the Python standard
library, never deserializes either `.pt` file and performs no model call, solver,
training update, fresh peer exchange or repeated numerical experiment.

`PASSED_BOUNDED` means that these exact archived bytes and their recorded
identity links agree. It does not repeat or extend the original numerical
acceptance. The model-state digest is a linked statement from the retained cold
result, not a state digest recomputed from a deserialized checkpoint.

## Interface and failure behavior

Run `python -B evidence_bridge.py /absolute/path/to/retained/v5` to print the
archive report. The root must use the retained layout already produced by V5;
input records do not choose file paths. Files are bounded, regular files and
checked for mutation during reading. JSON rejects repeated keys, nonfinite
numbers, excessive size and malformed objects. Every file is matched against
its exact byte count and reviewed SHA-256 before parsing.

`assess(records, candidate_sha256)` returns:

| Status | Meaning |
| --- | --- |
| `PASSED_BOUNDED` | Complete V5 archive identity linkage only. |
| `INSUFFICIENT` | At least one pinned archive role is absent. |
| `REJECTED` | An existing role is corrupt, a role is unknown, the candidate is different, or a link contradicts the retained record. |

A complete archive still reports `INSUFFICIENT` separately for real independent
A→B→cold reuse and old-capability retention **from these 14 V5 files**. It does
not rule on later, separately admitted evidence. For example, a new result for
this candidate on an old synthetic panel must retain its own scope and may
support a bounded retention claim; it does not become real-user provenance.
The module provides no authority
switch, arbitrary callback, supplied attestation store, signature parser or
synthetic path to scientific acceptance. Caller-provided authority roles are
rejected. The command's zero exit status covers archive linkage only.

## Connection to existing native intake

The existing `adoption_closure_v2.intake_contract` defines the original roles
`a_failure`, `a_success`, `a_train_consent`, `a_enrollment`,
`b_evaluate_consent`, `b_enrollment`, `b_future`, `keep`, `b_use_first` and
`b_use_again`. This bridge reports the missing roles using those names. It does
not create substitute enrollment or consent records.

At the reviewed commit `25c2cb2b60446a5f7692945bd154b0d8deb485f3`,
`native_adapter.authorize_owner` refuses with `ORIGINAL_TURN_VERIFIER_REQUIRED`.
At reviewed commit `477afcddffa755164469618ace9f4737bd4dd681`, the paired cold
loader admits Coding Cell and the declared Circuit profile; it does not admit
SmallHCSN by changing a family label. These are exact reviewed-source boundaries,
not assertions about uninspected later native changes.

The V5 trial and cold records explicitly state `genuine_independent_users=false`,
`natural_task_benefit_claim=false`, and `candidate_adopted=false`. Their two equal
final margins concern the same engineering fixture. Distinct hosts therefore do
not satisfy the existing distinct-person authority and new-task requirements.
`parent_restored=true` and unchanged original files establish trial isolation;
they contain no paired result on a frozen old-capability panel.

The protocol bytes bind recorded thresholds and budgets. This retrospective
bridge does not authenticate their registration chronology. A future scientific
admission requires the original owner's event chain and a reviewed verifier
adapter for that exact profile. Until that exists, this bridge deliberately has
no scientific-pass branch.

## Review and validation boundary

`evidence_bridge_tests.py` contains a bounded archive validation suite. The root
executes it once after source review and repository formatting, using the exact
retained V5 files. Tests cover corrupt bytes, missing evidence, old-candidate
substitution, source/task/protocol/receipt splicing, false provenance promotion,
preservation of the original failure, strict JSON and absence of framework
imports. They do not load or execute any model and do not reopen E1–E6.

Source inspection alone is not a test result. This proposal was prepared without
running this module or the suite. Root execution evidence must be retained
separately and must not promote the two scientific claims from `INSUFFICIENT`.

## Pinned source references

- [Existing native adapter](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/25c2cb2b60446a5f7692945bd154b0d8deb485f3/qualification/pft_six_experiments_20261125/adoption_closure_v2/native_adapter.py)
- [Existing intake roles and staged prefix](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/25c2cb2b60446a5f7692945bd154b0d8deb485f3/qualification/pft_six_experiments_20261125/adoption_closure_v2/intake_contract.py)
- [Paired model loader and evaluation panels](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/477afcddffa755164469618ace9f4737bd4dd681/scripts/cell_experiments/paired_cold.py)
- [Original-person checks](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/477afcddffa755164469618ace9f4737bd4dd681/scripts/cell_experiments/paired_people.py)
- [Candidate freeze and later task assembly](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/477afcddffa755164469618ace9f4737bd4dd681/scripts/cell_experiments/paired_freeze.py)
