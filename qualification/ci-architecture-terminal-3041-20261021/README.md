# Continuation Architecture source and base lane evidence

The original Architecture run
[39591475937](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39591475937)
has successful source-head and base-merge lane jobs for continuation source
`52293403ea1e06465c41d24d39b54959bad40936` and base
`48177153ad04605338c3a9a8dbd17defee9981bc`. Both lanes report tree
`8944830c3b3ed494987d01ef631ab48b69e75d1c`. At the recorded 12:39:53 UTC
observation on 2026-10-21, the aggregate `Architecture required` job
`119220992411` remained queued. These lane successes do not establish a
completed required aggregate or complete PR qualification.

## Original execution and exact scope

Source job `119193229802` completed at 12:27:40 UTC. Its original artifact
contains 31 command receipts, including the compiled service lifecycle,
migration, process restart, runtime ABI, supervisor and inference tests.
`command-verification.json` checks every command's original return code and
status, declared minimum test count, observed failures, timeout/output limits,
raw log byte count and SHA-256, and clean source identity before and after.
All verified commands returned zero and met their original declared checks.

Base job `119193229282` completed at 11:56:05 UTC. It tested synthetic commit
`97a4e30ae7f54d542bea19c4bc9465662249252f`, whose parents are the base and source
above and whose tree equals the source tree. The original workflow's same-tree
deduplication executed four repository/provenance commands in this lane and
requires successful source-head execution. It did not run a second native
build. Its four original records and logs are separately verified.

The original candidate-transport observation is advisory: HTTP 403,
`observation_status=unknown`, `admin_denial_proven=false`,
`credential_separation_proven=false` and `activation_authorized=false`.
The transport observation is preserved without claiming that an administrator
write restriction was proved.

These results cover the recorded 522/481 source and base only. They do not
qualify the later durability source, its new Windows paths, or the advancing
base branch of PR2968.

## Complete preserved artifacts

| Original artifact | Local file | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| 12346106677, source-head | architecture-source-52293403.zip | 99,339 | `8c824951057a2fd9754d09bd3a4ada0ae43a568a6f86e3cd1b565f376053fade` |
| 12343452565, base-merge | architecture-base-481-52293403.zip | 11,321 | `1a2f66c5cdcf5270144d1825ac5df422efcd5a7323c436ffdf368a4c8af71916` |

The two original ZIPs are intact. Their SHA-256 digests match both the original
Actions artifact metadata and upload logs; ZIP CRC and all 65 source / 11 base
member hashes have been verified. Companion JSON files and
`artifact-verification.json` preserve their identities, member sizes and hashes.

Both complete job logs are losslessly archived as XZ, preserving the
connector-decoded UTF-8 bytes including BOM and original line endings.
Companion receipts record original job steps and raw/compressed sizes and
digests. No workflow, source assertion, scope, permission, timeout or gate was
modified by this evidence collection, and no job was cancelled or rerun.
