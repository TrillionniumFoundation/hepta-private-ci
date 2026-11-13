# Independent peer: Root CURRENT across UID boundaries

**Result:** the frozen proposal is supported as a design/HOLD. Existing APIs alone do not implement the cross-UID task/custody path. No specific false completion or authority claim was found.

Reviewed proposal: c50a9352a3b3926385c1d741f7b7ecad63d2276f; original source cc57c7198db6293ccca562253c42fffbe2a04633; prepared Root86 view 3f7d40d4933669da33d2aef3491efb431c5771ae.

The complete original initial/retained preparation, actual journals, Artifact selection/withdrawal, independent FinalUse claim and dispatch, protected CAS, live Current-before/Artifact/FinalUse/Current-after checks and cold recovery are accounted for in REVIEW.json. Its input inventory contains all 22 proposal sources plus 8 independently full-GET source objects.

The minimum immediately reusable unit is a trusted-Root-local one-operation coordinator retaining the original Prepared/Ready and real journal locks. A separate reviewed sealed task/live handoff is still required if A/C stay non-Root. Same-task retirement must run with the same task/Cell Arc and actual Source; cold predecessor reconstruction already requires a Published successor and cannot supply the first completion circularly. Version's concrete control, Artifact owner and original-A Source observations also need explicit integration. A remote current=true response or a publication receipt does not meet those types.

Two clarification points are retained: historical task/completion cloning is not a new grant, while Prepared/config custody is consumed; original explicit forward-recovery APIs exist but require a distinct operator operation/signature and are not automatic lost-ACK retries.

No source or author proposal was edited. No H, compiler, formatter, Rust, QA, candidate main or gate ran. No new Root permission, generic callback, extra connection, request budget or real task-chain claim is made. B/Panel remains ordinary_path's sole-writer scope.

verify_inputs.py only hashes frozen source/GET bytes; it never imports candidate code or executes source tests. INPUT_VERIFICATION.json records that pure comparison. All paths in PLACEMENT.json are relative to the existing evidence leaf.
