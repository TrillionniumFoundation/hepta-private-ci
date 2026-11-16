# C2 original parent checkpoint recovery

Status: **EVIDENCE ONLY / HOLD**

This directory records a read-only byte-identity recovery performed after the live
replay-directory inventory in Draft PR #6308. It does not change or rerun either
historical replay.

## Closed item

A complete selected-domain scan covered every non-symlink top-level directory under
`/home/qian-qi` whose basename contains `hcsn`.

- Durable job: `1a1d8312d92-392-ccc`
- Idempotency key:
  `hcsn-c2-selected-hcsn-roots-parent-sha-scan-20261114-c06d-v1`
- Selection: 61 roots, 64,901 file entries
- PT files hashed: 621
- Scan cap reached: no
- Read errors: 0
- Exact original parent matches: 6/6
- Torch imports, model executions, optimizer calls: 0 / 0 / 0

All six matches are the `last.pt` files in one retained lineage:

`/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/campaign-v2`

`RECOVERY.json` binds each fit to its exact host path, size, link count, and SHA-256.

## Preserved negative and incomplete observations

The record also preserves, without relabeling:

- the initial facade `INVALID_ARGUMENT` refusal before any job existed;
- job `1a1d82e25b3-392-cc2`, which failed before Python started because its
  historical worktree cwd no longer existed;
- two bounded home scans that reached their 100,001 and 500,001 entry caps and
  therefore could not establish a whole-home absence;
- exact inspection of the immutable 11,397,159-byte export ZIP with SHA-256
  `37d387507ec150abfdad4065c23612e18fca6643d489f3555874c8e57a514b75`,
  which contains six known later checkpoints and 0/6 original parent matches.

These earlier results remain valid within their stated scopes. The successful
selected-domain recovery does not rewrite them.

## Remaining HOLD

This closes only the missing exact byte paths for the six original parent
checkpoints. It does not deserialize them and does not establish model, Adam, RNG,
cursor, start-parent, remaining-wall, allocation, concurrency, calendar, or
source-runtime completeness.

The historical desktop replay `1a1c74f3308-be2a-75` remains non-authoritative
`UNKNOWN` and was not restarted. Full independent training replay remains
`0/6`. No production adoption is authorized, and `all_closed` remains false.
