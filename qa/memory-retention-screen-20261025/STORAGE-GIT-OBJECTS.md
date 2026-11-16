# Historical archive location

Oversized original archives or receipt files from this directory are retained
exactly in the reachable incoming Git history. Their original paths, source
commit, blob IDs, lengths and SHA-256 hashes are indexed in
`qa/repository-consolidation/20261115/memory/HISTORICAL_ASSETS.json`.
See the adjacent `HISTORICAL_ASSETS.md` for the checked offline restore command.
The restore tool requires the original source commit to be an ancestor of HEAD
and writes only into a new external directory. Historical results are not a
current test or model qualification.
