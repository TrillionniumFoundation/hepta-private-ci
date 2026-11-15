# Model CURRENT journal receiver repair

Status: prepared child of `7dd5b5efe75de6a950f0c9ba9acf6856f6df997e`. This repair has not run Python source tests, the whole-workspace caller verifier, Rust compilation, native mechanisms, or ordinary acceptance.

## Actual failure

The complete caller verification on source `4537458b51b6ca936264aecea7cfe384b941d0d1` terminated with actual exit 1 after 1318.145882 seconds, inside the original 4800-second budget. Its 191-byte stderr is blob `7234209c4e5cea9db2f43bb4e3503459d96ecf0d`; original terminal receipt is `d442b61a89ce1ab3f41e2dac82a21f583fa00479`; complete result is `95affec002c5589295c90df4bb943d16ba25ea5e`. Root preserved those results in evidence commit `2facbab69deb479e948a42b19b6f64f221aacf7e`.

The error was an unresolved possible `CellQ24ModelProposalOwnerV1::readback` receiver in `cell_q24_model_current_owner.rs`. That split impl contains two method-style reads of its original durable journal. The actual field is `LockedFileProductEvaluationExecutionStoreV1`, whose implementation of `ProductEvaluationExecutionStoreV1::readback` supplies these operations.

The unchanged conservative scanner indexes fields of the authority type being checked. It therefore does not assign the unrelated journal field a Model-owner type. Both ambiguous calls must remain rejected unless their actual receiver is made explicit.

## Repair and regression

The two calls now use `ProductEvaluationExecutionStoreV1::readback(&mut self.journal, &admission.key(self.binding))`. Only call spelling changes: the original journal, mutable borrow, key expression, Result handling, physical reads, time checks, and permanent fences stay in place.

The existing Model proposal QA now includes the actual split impl in its source index and checks the four already registered CURRENT-owner boundaries alongside the original eight. Within the existing test method, it independently restores each real call to the ambiguous method syntax and asks the unchanged original verifier to reproduce the precise unresolved-receiver rejection. The original unregistered-caller checks and all eleven test methods remain.

`CALLERS.toml` stays byte-identical to blob `95c8261a6c3eec23d038ba5aec754d618731d222`: 737 boundaries and 506 complete protected records, including all root metadata, authority declarations, and repeated-path records. No allowlist, verifier, resource budget, permission, or production owner interface changes.

## Evidence limits

`repair-audit.json` contains the real receiver chain, fixed source pins, exact forward/inverse edits, original failure receipts, the six-file static projection, and preserved inventories. The V8 projection found the expected twelve caller sets and rejected twelve unregistered callers and both real-call rollbacks. This is a bounded algorithm projection; it is not execution of the Python verifier or a whole-workspace result.

Expected inventory remains 445 source methods in 62 modules, 201 native cases in 43 groups, and the separate original 29 Root cases. Ordinary acceptance remains zero. Source453 results belong to source453; no result is transferred to parent7dd or this repair.
