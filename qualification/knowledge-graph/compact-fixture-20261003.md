# Compact generation evidence fixture and private argument groups

## Source-bound observed results

At `f3effae2d6de766e40de0d79e70b3756eaceb0c9` (tree
`9047462ec306658ec568d50eaaa98c6f436afc11`), hosted run `37118027050`
executed both exact source and deterministic merge. Each passed 35 KG, 55 prompt
registry, 51 optimizer, 278 Memory owner, the explicitly ignored crash/reopen
case (1), and the default product profile (9; four declared skips). The source
capacity case passed all 256 writes, 20 queries and five ordinary reopens in
586.067 seconds. This is a runner-specific PERF-LIBRARY measurement, not target
host acceptance. The actual production-daemon custody gap remains unchanged.

Both lanes failed the qualification writer profile: eight passed, one failed.
The remember/restart/correct/forget E2E stopped at its own evidence assertion,
`current projection rows did not match their generation receipt`. The helper
counted legacy `kg_nodes`/`kg_edges` snapshots even though the selected algorithm
stores `revision_facts_v1`. The same verified capacity receipt reports zero
legacy snapshot rows and the expected 4,096 entity/32,768 relation revision facts.
Strict Memory lint separately failed the two private eight-argument functions.

Source artifact `11273280643`, ZIP SHA-256
`9aacb87c9795bd971fca3ddc83d161bebfd4b4fe0dd16e6837c6324268554da6`:
23 checksum entries and all eleven command identities/logs verified.
Merge artifact `11273170565`, ZIP SHA-256
`1c0908c9fecc396b98f3b7523403a7fffd82ba2ab8eeb07711bc09b94f593167`:
21 checksum entries and all ten command identities/logs verified. Merge
`5c2b4e5a855e1d73c16a227154e74800a936f16d` has the exact source tree and ordered
parents `ad0ff102422a64f947763156ca68935f218010c4`, `f3effae2...`.
No duplicated execution receipt or new positive qualification flag is created.

## Repair and tests

Only the read-only E2E evidence query changes storage interpretation. All its
reads now share one transaction. It requires the compact-storage witness, selects
the latest immutable revision trigger at or before the exact current generation
for every memory in that scope, and counts verified active revision membership.
The source citation, immutable fact-set, canonical generation, publication and
receipt/count checks remain. No production SQL or acceptance check is relaxed.

Six Python regressions execute the actual SQL extracted from that Rust fixture.
They cover complete multi-memory cuts, correction, retained tombstones, missing
facts, wrong trigger, missing/unknown storage witness, foreign scope, future
revision and unverified latest-head exclusion. These fixture-query results do
not substitute for the current candidate's real daemon execution. The runner
records this regression group with a nonzero guard before the native groups.

The reviewed `f2661efafcd4bef72ec22c37ed4947f19ca1e1de` private parameter groups
are applied as three minimal hunks. Public APIs, SQL, validation order and receipt
construction are unchanged. Outbox postimage `93aef85620e753a6f49d486eaee436f8ac3edde1`
and production-writer postimage `fd9fa46e14576f78a872a5aee524b46d04cde593`
exactly match that prior reviewed patch. The cognitive writer has newer bounded
history verification than the old patch; that complete paged/streamed body was
preserved byte-for-byte, not replaced with the older file.

Six SQL regressions and seven recorder tests pass locally. Scoped formatter,
Python lint and whitespace checks pass. No local Rust build or paused-path change
was made. Hosted native results for this follow-up remain pending; f3's passing
capacity result is not relabeled as a new-source pass. Historical sourceBase,
all prior claims, unrelated maps and every false acceptance flag are retained.
