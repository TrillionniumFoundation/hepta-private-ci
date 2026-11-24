# App-server export synchronization — 2026-11-24

The original Windows shard for #6995 at
`07c8994f2402a58f6b59eb648c801fc40c6e2b96` failed the stable precomputed,
experimental precomputed, and JSON fixture equality checks. Its schema source
and checked-in export archives did not describe the same already implemented
API. This change runs the repository's generators; it does not add methods or
change experimental gating in the Rust protocol definitions.

The stable archive was missing nine TypeScript entries and two JSON entries.
The experimental archive was missing fifteen TypeScript entries and eight
JSON entries. Both archives also needed their request/index/bundle references
refreshed. The stable internal rollout schema was regenerated. No export is
removed. The existing `TurnRecoverResponse.json` now includes the already
defined `completed` sub-agent activity value.

Validation on Rust 1.95.0, nextest 0.9.103:

```sh
just write-app-server-schema
just write-app-server-schema --experimental
just test -p codex-app-server-protocol
just fmt
```

Both generators succeeded. The project test run passed **303/303** executed
tests, with the existing generator-only test skipped. All three originally
failing equality checks and the TypeScript fixture check passed. The project
test execution took 4.023 seconds, separate from build and metadata time.
The cold stable generator build took 6m34s; this is build work, not test time.
The precomputed archives were decoded and their added/changed/removed entries
reviewed. Platform CI remains a separate qualification of the published head.

No Cargo manifest or dependency lock is changed by this patch.
