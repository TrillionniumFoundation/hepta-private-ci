# Original Fence v0.13 audit-mode qualification

The one original push run **43055103354**, job **130642329146**, attempt **1**, completed successfully. The job started at `2026-11-11T16:08:48Z` and completed at `16:13:15Z`. All 14 job steps, including the final Fence post hook, succeeded. This packet preserves the complete original job log, the complete original Actions artifact ZIP and its nested archive, full API snapshots, the frozen preparation and the actual admission record.

## Fixed identities and actual checks

| Item | Actual identity or result |
| --- | --- |
| Source anchor | `c89540598693697577cda8cba31cb07f6ce65317` / tree `5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae` |
| Isolated harness | `0e92c37a012733882ce4c120afc38b6757edb7cb` / tree `60f86e9520355850e289769a83dc2bcca2f26811` |
| Branch | `codex/mem8-fence013-qualification-20261111-ed353817` |
| Complete Fence Action | `c7675fea986c29f1d655753a7a61fd6b4141be8f` |
| Reviewed upstream source and bundle signer digest | `64acdc94f531728494efbdf2d8f05faa26e90f7a` |
| Actual binary | 2,203,880 bytes; SHA-256 `1a1ac7ad60216e7803403645c202e8c8a4e738326350ce340f8138df1c9a5e04` |
| Original policy unit tests | `Ran 7 tests in 0.685s`, `OK` |
| Original blob policy | 1 changed file checked against the unchanged 512,000-byte limit |
| Final Fence report | `healthy`; network `verified`; sudo and containers `preserved_verified` |
| Mode and protection boundary | `audit`; `ready_observation_only`; `protection_available=false` |

The actual binary is retained in the original nested archive. All seven Action file contents match the frozen pins before and after the original checks. The Action makes its own files read-only and the binary executable during setup; the recorded access-mode changes are retained and are not described as mode equality. All seven file contents remain equal.

Both source snapshots are clean and have identical complete `git ls-tree -r -z` bytes. Independent Git Merkle reconstruction yields the 14,054-leaf harness tree. Removing its sole added workflow reproduces the 14,053-leaf source anchor tree. The five original policy files, including the allowlist, checker, tests and clean-worktree action, are retained in full and unchanged. The original six job steps were preserved apart from observation IDs and the reviewed Fence pin. The runner, audit input, 30-minute budget and downstream threshold remain unchanged.

## Reproduce the evidence audit

From this extracted packet, run:

```sh
python3 verify_fence013.py . --compare-audit
```

This uses only Python's standard library. It checks the complete original ZIP digest and CRCs, all four ZIP members, the 114 regular nested archive members, every one of the 113 inner manifest entries, all action and source bytes, the two full-tree Merkle roots, original command receipts, original run/job identities and times, the literal capture program embedded in the workflow, all policy counts, and the final post report in the original full job log. It also checks every outer package member against `MANIFEST.json` and compares its complete result with `AUDIT.json`. It does not execute the bundled Fence binary, the capture script, Git, tests, a host or a network request.

The original artifact is stored as `original/ORIGINAL_ARTIFACT.zip`. It contains the complete `mem-fence013-qualification.tar.xz`; the verifier reads both containers directly without requiring a second expanded copy. The complete original log is `original/original-job-130642329146.log`. Full API response objects and the original tool response wrappers are retained. Temporary signed download URLs and duplicate local transport copies are excluded.

## Scope and limits

The artifact was uploaded before the checkout and Fence post hooks. Its original `qualification_result: NOT_FINAL` and unobserved-post fields remain unchanged. The later terminal API snapshots and the complete original job log supply the final post result. Source snapshots bracket the original policy checks; there is no separate source snapshot after the post hooks.

The push comparison range is the isolated one-workflow child of `c895405`, so this run checks one changed file. It qualifies this fixed Action with the original policy mechanism on the stated runner. It does not establish that the entire PR #5935 diff or the complete hosted CI matrix passed. Audit mode observes traffic; this packet makes no block-mode enforcement claim. The historical v0.10 `local_control_inventory_unavailable` subreason remains unknown. No model request, Rust native test, new production owner, memory benefit or adoption-gate closure is claimed.

Preparation files describe their original pre-admission state and are preserved verbatim. `preparation/ACTUAL_ADMISSION.json` records the actual later admission; `AUDIT.json` records this final evidence result. No old execution record has been overwritten or retried.
