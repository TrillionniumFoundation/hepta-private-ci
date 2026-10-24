# Fixed-graph evidence publication

This publisher only reads retained experiment artifacts and writes a new
publication. It does not call a Runtime worker, model, reducer, original reporter,
or recovery owner. The actual independent primary and recovery audits have
already completed; their exact bytes and explicit partial scope are pinned.

## Exact target and transfers

The original graph worktree is
`/home/qian-qi/workspace/hepta-cell-graph-benchmark-20261024`, branch
`research/cell-graph-placement-20261024`, HEAD
`4435d4b93e130d12bfc24c45ead93fb4a30c4577`.

The existing evidence is
`/home/qian-qi/workspace/hepta-cell-graph-evidence-20261024`.
The publisher archives this directory locally on main; it does not transfer
each original file back through the operator API. It rejects symlinks, special
files, changed files and over-limit input (4,096 files, 256 MiB total, 16 MiB per
original file). The compressed archive must be at most 64 MiB. Exceeding a bound
requires an explicit reviewed correction; files are not silently dropped.

Transfer the three prepared assets to an experiment-owned sibling directory:

- `publish_graph_evidence.py`;
- `publication-spec.json`;
- `local-source-and-receipts.tar.gz`.

Use the exact hashes/sizes in `BUNDLE_HANDOFF.json`. A create-only bounded
chunked upload can carry the compressed bundle. The complete local bundle
includes graph-only sources, all earlier source/failure history, independent
reviews, actual audits, exact original failure capture, local copy timeout and
reconciliation receipts, C's successful upload sidecars, and the retained
through-A/B/C states. The three existing per-case journal archives remain
pinned in the remote evidence root; all three are needed for their union.

Suggested assets directory:
`/home/qian-qi/workspace/hepta-cell-graph-publication-20261024/assets-v1`.
Suggested fresh state directory:
`/home/qian-qi/workspace/hepta-cell-graph-publication-20261024/run-v1`.
The state directory must be absent before prepare and must remain outside both
the repository and the evidence input tree. Keep the asset-transfer receipts
outside the bundle they acknowledge.

## Prepare and inspect

Run through the existing original process owner with `/usr/bin/python3` and
explicit arguments. `EXPECTED_SPEC_SHA` below must be replaced with the frozen
SHA from the reviewed handoff, not calculated from an untrusted new spec.

```bash
/usr/bin/python3 /home/qian-qi/workspace/hepta-cell-graph-publication-20261024/assets-v1/publish_graph_evidence.py prepare \
  --spec /home/qian-qi/workspace/hepta-cell-graph-publication-20261024/assets-v1/publication-spec.json \
  --spec-sha256 EXPECTED_SPEC_SHA \
  --bundle /home/qian-qi/workspace/hepta-cell-graph-publication-20261024/assets-v1/local-source-and-receipts.tar.gz \
  --state /home/qian-qi/workspace/hepta-cell-graph-publication-20261024/run-v1
```

A bounded 600-second native owner timeout, at most two CPU ceilings and 1 GiB
memory are sufficient operational caps; this publication is not a performance
sample. No service, deployment, dependency installation or model is involved.

The gate checks all ten protected original source pins, exact dispatch/export
identities, all 18 owner/collection/reduction chains and 30 request/output
bindings, actual independent partial audit/report identities, the original
failed/absent/absent recovery, exactly four original raw chunks with no whole
ledger, the two prefix artifacts and all three corrected recovery archive SHAs.
It retains every regular file under the bounded task evidence root, including
failed/partial records; nothing is selected by positive outcome.

Before installing anything, it builds and rereads the complete compressed
archive and verifies its member census/hashes, then verifies the input tree
again. It creates only the new repository directory
`qa/stem-bakeoff/evidence/cell-graph-placement-20261024/`. Existing source and
evidence files are not replaced. The readable report/audits, original remote
archive, local receipt/source bundle and complete per-file manifests are all
listed in the new `FILE_MANIFEST.json`/external `PREPARED.json`.

Inspect `PREPARED.json`, its complete census, the repository file manifest and
`git diff --stat`/status. The final source, tests and this runbook are also inside
the local bundle. No original experiment needs to run again.

## Commit and push once

Use the same exact arguments, replacing `prepare` with `publish`.

This stage requires unchanged base HEAD, exact installed bytes, no unrelated
tracked/index/untracked changes, a GitHub origin for
`TrillionniumFoundation/hepta-private-ci`, and the original remote branch still
at the expected base. It stages only the new publication directory, checks the
entire staged census and whitespace. It checks each index blob against the
prepared byte count/SHA, obtains `git write-tree`, verifies the resulting
immutable tree's complete delta/content, and records that tree and original
parent in the exclusive commit intent. It makes one ordinary commit, then
requires the exact recorded tree and exactly one parent at the original base,
with a clean worktree and unchanged original sources. It issues one non-forced
push of the recorded full commit SHA to the explicit branch and reads back that
branch using `git ls-remote`. An index or commit-hook mutation is retained and
blocks the push; it is not accepted just because the resulting worktree is clean.

Only an exact observed remote HEAD qualifies publication. The exclusive command
intents, stdout/stderr, return codes, observed times and final push observation
stay in the outside-repository state directory. A push timeout/nonzero exit is
retained even if the following read confirms that the commit reached the remote.
The final acknowledgement cannot be in its own acknowledged commit/archive.

`PR_BODY.md` is the complete replacement draft for #3676. Root may apply it after
the commit is confirmed, using a structured body argument or `--body-file`.
This publisher does not edit the PR, merge it or deploy anything.

## Failure and uncertainty

Every attempt creates exclusive intent files. Repeating `prepare` on the same
state/destination or repeating `publish` on its original intent is rejected;
no old evidence or acknowledgement is overwritten. A failed preparation keeps
its outside-repository staging and any partly installed new directory for
inspection. A staging/commit failure leaves the original index/worktree state
visible. It never resets, amends, deletes failure evidence or silently retries.

If `COMMITTED.json` exists but the final push acknowledgement is missing, use
the same arguments with `confirm`. That command checks the exact existing
commit/files and performs only a fresh read of the original remote branch. It
does not make another commit or push. If the remote remains at another commit,
the owner must investigate the retained failure and decide the next exact action;
there is no automatic merge, rebase, force push or repeated effect.

All publication timers cover only their explicitly recorded new stages. The
original 4/34-chunk, 45/383-record loss, missing sealing/outer/helper costs and
unmeasured native-service/owner CPU/RSS remain unresolved. Neither this publisher
nor successful new custody turns the original complete-cost flag true.
