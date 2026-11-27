# Merged helper branch cleanup

The three helper branches from merged PRs #7171, #7172 and #7173 were deleted
after their original tips and ancestry in candidate `73a86e4c0f7b6d4772dc259796f7492323acb539`
were checked. The final receipt records one successful atomic GitHub GraphQL
`updateRefs` mutation using each original `beforeOid`, a zero `afterOid` and
`force: false`, followed by fresh absent-ref and retained-candidate/main readback.
The [official API contract](https://docs.github.com/en/graphql/reference/git#updaterefs)
defines those compare-and-swap and atomic batch semantics.

These files preserve the original bytes of the successful cleanup receipt and
both earlier Git transport failures. The first push timed out after 90 seconds;
its exception is recorded in `merged-helper-cleanup-20261127-589c.json` and no
separate stdout log was produced. After terminal-process and unchanged-tip
reconciliation, the same original leases were tried once more; that attempt
exited 128 after 300 seconds with the connection error in the adjacent log.
The final GraphQL operation did not weaken or replace those original SHA guards.

This evidence covers these three merged helper refs only. It does not qualify
the HIA product, authorize deleting other refs, or retire legacy source.
