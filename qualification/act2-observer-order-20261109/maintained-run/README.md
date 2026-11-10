# ACT-2 maintained observer source: fresh native qualification

**Scoped result: PASS on exact source `8b1c1789916514471c6cacdf0f6c45467255fef9`. Full ACT-2 promotion: HOLD.**

[Run 42769615520](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42769615520),
attempt 1, directly executed the maintained observer candidate. Its original
artifacts are retained here. These results are read from this run's records and
logs; they are not transferred from the preceding `111d5773` execution.

## Exact identities

| Role | Commit | Tree |
| --- | --- | --- |
| Hepta actual tested source | `8b1c1789916514471c6cacdf0f6c45467255fef9` | `b9879a77f0b7a7d8f766aaf2308b719e6bcaa29e` |
| Source parent | `111d5773145dbe4add99a28b2d1111916a3dbd3b` | Recorded as the single parent in all command records |
| Pinned Session/App companion | `fd8d56c52b971c2d5d0e6430f296803b43ef60a3` | `347fbb7e9931006c749b5bef0e1550c54bc08f27` |

Native job `129674076235` and independent formatter job `129674076507`
completed successfully. All five wrapped commands record the same clean source
commit/tree before and after execution. Scoped `just fix` changed no source.
The independent `format.patch`, native `final-source.patch`, and final
`source-status-after.txt` are all empty. Both empty patch hashes are
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
The 14 complete formatted-file records also match their recorded SHA-256 values.

## Original results

| Scope | Result from this run | Outer command elapsed |
| --- | --- | ---: |
| Automation package | 169 passed, 0 failed, 2 skipped | 219.651 s |
| Notes observer, projection and original owner | 10 passed, 0 failed, 778 skipped | 364.287 s |
| Pinned Session/App locked build | exit 0 | 87.585 s |
| Selected real Session/App lifecycle | 1 passed, 0 failed, 787 skipped | 2.780 s |
| Scoped lint/fix | exit 0, source unchanged | 209.923 s |

The Notes log explicitly reports PASS for both added observer-order tests:

- `notes_document_observer_clones_fence_revision_and_content_without_writing_effects`
- `notes_document_observer_clones_do_not_queue_behind_an_inflight_exchange`

Every command log's byte length and SHA-256 was checked against its original
record. The three nextest summaries agree with the recorded pass counts and the
separately reported skipped counts. All commands returned 0 without a timeout
or output-limit truncation. Existing warnings remain in the original logs.
Outer elapsed values include compilation and runner work; they are not policy
performance comparisons or scientific trial durations.

## Actual App observations

[The exact current-document JSON](notes-actual.json) was independently checked:

- The first original goal was terminal/succeeded at revision 1.
- Later real edits reached revision 3. The first historical applied receipt
  remained, while that old current goal was unsatisfied and its runtime UNKNOWN.
- The recovered third operation was terminal/succeeded at revision 3; three
  fresh repeated complete status values were equal without extra effects/grants.
- After the owned App was closed, actual readback returned Connection refused.
  The original owner remained Committed with its applied receipt, while the
  current document was missing and the current goal/runtime were UNKNOWN.

The lifecycle records 3 effect attempts and 4 issuer requests across three
operations, including the deliberate issuer denial. Recovery requested no new
grant and replayed no effect. These observations are correlated parts of one
App lifecycle, not independent trials. Neither an actual checkpoint rollback nor
the complete model-facing handler is exercised by this source. The later
model-tool-success repair in PR #5619 is not included here.

The recorded session/app executable hashes agree with the actual App JSON:
`6ec59c62cdeb4849d4c20a1234cac0c9b9fdd9dcbd9cae62cee31112aa409d7d`
and `5af4d1c90a172134942dc3a0bcd242a8c41e32cbc6274a5eddebd4383727715f`.
The archives retain recorded complete lock/executable hashes, not the complete
binary/lock bytes or a standalone Hepta test-binary hash. This audit does not
independently recompute those unavailable complete-file hashes.

## Preserved originals

| File | Artifact ID | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| [Native original ZIP](act2-native-42769615520.zip) | `13742246430` | 72,575 | `d49152b24616f101d4f92b736eb9a98e48a1277b255cad22e5b9315e3399f163` |
| [Formatter original ZIP](act2-format-42769615520.zip) | `13741570460` | 39,315 | `72206bfcd6aeddfe3e73b05673cd57bfe322ee9bff54fe93d70063a7b0c2bb6c` |

The ZIP bytes match GitHub artifact digests and were not repacked.
[RESULT.json](RESULT.json) retains all five command records, per-member hashes,
source/lock/binary observations, summaries and checked assertions.
[GITHUB_METADATA.json](GITHUB_METADATA.json) records this run, its jobs and its
artifact identities without temporary signed download URLs.

The fence remains limited to accepted document reads in one attachment.
Persistent rollback protection, destination cancellation/tombstones, global
report freshness, full handler qualification, production authority, native
kernel/pixels, complete repository CI and learned hierarchy benefit remain
separate open gates. This scoped pass authorizes no merge or deployment.
