# HPCA V2 OOD recorded prompt/condition provenance (2026-11-11)

**HOLD_NO_GO / DENY_ALL.** Read-only arithmetic audit, not independently executed inference or Owner attestation.

## Parent and provenance

- Parent: PR #5995, HEAD aaa01ecc3b4e157dcf4927ac42301daaf2df7b4c, tree e7542822d33e3eba2a9405cc04f9b7eea19dab43.
- Original auditor Git blob e7641286fae3b85e83117c5f6b2c5d4901b9a5b0; 11 tests Git blob d8dafd15d38c48466c304f9469208e12eeda54fd.
- Frozen 24-task plan Git blob fc9a27b78f7fef95d8f3b3235f269c3c24cc2c91; unmodified 216-row report Git blob 657d0bdd842c19756e497607b89f5b8019d596d3; report SHA-256 3002553ec485b19247f510863e9c78d2cce7747434ad7737f68b7dd3f9a74a2a.
- Original forward constructs the question after strip plus newline and Answer: suffix. The auditor had compared the declared prompt digests between arms only, without binding to frozen plan questions.

## Red/green test

The unchanged parent auditor accepted three falsifications: coordinated prompt-hash replacement across all nine arms, seed metadata changed while condition label remained, and a changed claimed training result identity. Three added negative tests reproduced this (15 run, 3 failures). See RED.log and RED_RESOURCE.log.
The repaired auditor verifies SHA-256 of exact frozen prompt-frame bytes for all 216 prediction rows; binds run seed/arm to condition and the original source training PR/digest. The original cross-arm mismatch rejection remains. All original 11 plus four new tests pass (15/15). See GREEN.log and GREEN_RESOURCE.log.
Local red resource accounting: 0.10 s wall, 0.09 s user CPU, 0.00 s system CPU, 22196 KiB RSS. Green: 0.09 s wall, 0.08 s user CPU, 0.01 s system CPU, 22500 KiB RSS. This measures tests only, not actual training/model costs.

The complete original audit was recomputed, and the output compared byte-equal to the original PR's AUDIT_RESULT.json. Four seed pairs retain all 96 identical binary decisions, accuracy differences 0. No new scientific efficacy evidence follows.

## Remaining HOLD gates

These digests are still operator records, **not proof of actual model inputs or source identity**. Production Owner-attested action and feedback timestamps, independently locked future B, real effects on distinct C, NoUpdate/Adopt with cold recovery, all-lineage controls, old-task retention, ACT/CTRL dense and sparse feedback, resource-complete Core×NDU 2x2 remain open. No production Cell or Agentd permission is changed.
