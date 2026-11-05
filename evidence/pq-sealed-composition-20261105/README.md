# Private Hepta PQ / sealed composition evidence — DRAFT / HOLD

This is an evidence-only package for the already published code commit **f55752abbf516febfa0db89cb833dcf1fd1a2221**, tree **039577d88899ddc1725f44dbf508e69d58506fe3**, in `TrillionniumFoundation/hepta-private-ci`. It contains private Hepta patches and source snapshots. Keep it in this repository; do not copy it to the Chain repository.

## Source history and exact result boundaries

| Identity | Meaning | Native result that may be claimed |
|---|---|---|
| `285b7510cf7f247b84a4c55fa349af77810a3b4b` (source tree) | Earlier repaired eval/intelligence snapshot | 218 PASS, 0 FAIL, 0 skipped on that snapshot only |
| `7ad4a974496e587f0ce863ce565cb74a98149b2e` / commit `5375d7d2774f7422d6c7c352188273e678746376` | Frozen sealed code on base `7530e4bc7aa61a0c23a5933fef4a65d86a586cf8` | Final 218 request rejected by disk guard before Cargo started; no final-source native PASS |
| `97ae5b4bf5e5f0d0589c1c653f1861e1d9c1242f` | Snapshot V3 / PQ Frontier V4 remote advance | This package preserves its 23-file source change; does not borrow another runner's test results |
| **`f55752abbf516febfa0db89cb833dcf1fd1a2221`** | Published merge with primary parent `97ae...`, secondary parent `5375...` | **No Cargo, Clippy, Agentd/infer typecheck, native installation or three-generation no-update run was executed on this commit** |

The first historical eval/intelligence run had 205 PASS and 13 FAIL. Those failures were strict final-holdout lineage integration fixture failures, not a demonstration against the original vulnerable source. The failing log, repaired source snapshot and subsequent 218-PASS log are all retained. Later no-update input retention, its unexecuted native assertion, formatting and one redundant-clone fix are recorded separately.

## Checks actually performed on the published commit

The Git commit objects were reconstructed from raw Git bytes and accepted only after their object SHA matched the published SHA. GitHub's JSON timestamps are UTC-normalized; the authenticated raw commit offset is `-0500`, and the message has no added trailing newline. Local HEAD was then updated with an expected-old-head check; index and code bytes were retained.

A separate read-only checker compared **all 11,710 tracked entries** against the committed tree using actual filesystem reads, not just `git status`: **181,087,282 bytes** hashed; **11,558** regular `0644` files, **151** executable `0755` files and **1** actual symlink verified. It checked symlink target bytes without following the leaf, rejected symlink ancestors, compared index path/mode/blob inventory, and restatted successful paths after hashing. There were no mismatches. The checker and receipt are in the archive.

On this real commit, Lane A `verify`, Lane A `self-test`, source registry closure and the exact-commit Lane A source receipt all passed. These are source, registration and truth-map checks. They do not certify native runtime behavior, production activation or independent system acceptance.

## What the archive retains

`evidence.zip` contains the private source patches, prior 218 source archive, final and composed source snapshots, source-change diffs, raw failures, default-graph resource stops, fixed-source manifests, verified remote advance, commit import proof, real tracked-byte proof, and published-commit source-check receipts. It contains no compiled binary or large build directory. `INDEX.json` lists every archived payload with its SHA-256 and byte count; the archive also contains an internal copy of the payload index.

Historical records retain their original paths, source identities, command arguments, timestamps and failures. They are evidence from their stated phase, not results on the current commit. Resource guards were not relaxed; the old `f_bavail`-based native refusals remain refusals even though privileged writes later allowed this small evidence package.

## Reproduction and remaining gates

After checking out the published code commit, extract the archive in a separate directory and run:

```sh
python3 payload/verify_published_tracked.py --repo /path/to/hepta-private-ci --commit f55752abbf516febfa0db89cb833dcf1fd1a2221 --output tracked-real-bytes.json
python3 scripts/verify_lane_a_foundation.py verify
python3 scripts/verify_lane_a_foundation.py self-test
```

The source-registry command and exact source-receipt command are recorded in their JSON receipts. All previous Cargo commands, pinned tool/configuration hashes and resource results are retained. Native tests must be performed on the same fixed candidate with adequate resources before changing HOLD status. This evidence-only package grants no merge to main, release, production activation or independent acceptance.
