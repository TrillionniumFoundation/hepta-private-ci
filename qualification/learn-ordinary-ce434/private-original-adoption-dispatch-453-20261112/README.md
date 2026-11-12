# Private original Candidate adoption dispatch

This independent child of `4537458b51b6ca936264aecea7cfe384b941d0d1` connects one existing concrete production path. It has not been merged into the PR, compiled, run on H or counted as ordinary acceptance.

## Production change

Root's private `require_stage` now sends Candidate Selection/NextUse through `require_original_adoption_stage`. The new crate-private helper first calls the unchanged `require_adoption_cut(..., Action::Execute)`, then requires the already-installed Root gate to exist.

That original predicate checks the full training/model cut, exact five receipts before Selection or six before NextUse, Fresh origin, the original coordinator's next stage and the original absolute deadline. Gate presence is a dispatch prerequisite. It is not a CURRENT read, an issuer decision or an effect authorization.

The actual runtime still performs original `gate.begin` before dispatch. Effects still go through `execute_original_evidence` and the same-operation opaque evidence consumer. Original current reads, full E/retention qualification, Model identity, Version/FinalUse issuance or denial, Selector/Observer evidence, actor independence, cancellation, expiry and post-CAS verification remain unchanged.

The generic Candidate `execute_stage` and `receipt_attestation` positive denials remain byte-identical. NoUpdate/recovered separation, existing public interfaces, principals, grants, keys, connections, resources and statistical rules are unchanged.

## Source protection

`CALLERS.toml` changes from 736 to 737 boundaries and retains 506 complete protected records. Only the complete Root stages and Candidate adoption protected records change. The other 1,240 complete boundary/protected records remain as their original raw text, including duplicate paths; all seven original root authority flags remain false.

The new boundary has one exact caller: the private Root stages module. Existing empty ordinary factory/launcher caller declarations stay empty.

The live `route-current-contract.json` is updated with those exact full records. Its 69 existing deletion cases, 12 private injections, 24 historical boundary changes and eight historical boundary additions remain. Five new deletion cases cover the new dispatch. The original resident source QA retains all four methods and adds two methods with 46 deletion/replacement controls for the exact cut, gate presence, generic refusal, cancellation, deadline and actual CURRENT boundaries.

Expected source inventory is 445 methods in the same 62 modules. Native inventory remains 201 cases / 43 groups, plus the separate original 29 ignored Root cases. These are expected inventories, not new execution results.

## Verification and limits

Static forward and inverse edits recover the complete original production files. V8 projections of the existing verifier rules accept the 13 current contract records and reject all 74 contract deletions, 12 private injections and 46 new resident controls. The original Python verifier, complete caller scan, compiler and native tests have not run for this child.

No runtime positive eligibility or complete resident 5→6→7 mechanism is claimed. The existing Root Model projection fixture has real SourceBound T/Model inputs but explicitly uses fixture E/Product metadata; it does not transfer the original Fresh common/Trainer/Version/C ownership needed by the Candidate constructor. `mechanism-feasibility.json` records the exact fixed interfaces and the missing transfer. No gate, Qualified signature or Fresh tag was fabricated to produce a pass.

Ordinary A→B/retention→S/Version→new-session, different-content C→true daemon/Root restart remains unverified. The prior ordinary input/custody review is archived separately and remains historical to source453.

## Evidence

- `production.patch`: the two exact Rust edits.
- `source-guard-audit.json`: full before/after records, exact pins, counters and static scope.
- `guard-projection.json`: individual V8 projection results, explicitly not Python execution.
- `mechanism-feasibility.json`: actual fixture ownership boundaries and untested scope.
- `prior-ordinary-wiring-audit.json` / `prior-ordinary-wiring-README.md`: the earlier source453 review, retained unchanged.
- `maintenance-inert/`: unchanged non-executable maintenance draft, null binding and independent review. It still refers to historical v2 runtime/old main pairing and cannot be dispatched; no future v3 identity or result is filled in.
