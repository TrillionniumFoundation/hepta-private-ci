# One protected HIA tip refresh

This append-only refresh extends the previously published full-history export.
It records exactly one captured ref advance: codex/hia-chrono-time-network-proxy-20261119-a11
from c32019b1e1ef566419a7b6d28a34d24270cf3d27 to 5653790ac0f64783c28926dcfca2fa7a48a40e77.

The actual new commit object was fetched with tree:0 filtering, --no-write-fetch-head,
and an explicit SHA only. Native Git verified its object identity and sole parent.
No local tracking ref, FETCH_HEAD, remote ref, original audit/export, production
manifest or reviewed source was changed.

Each .gz file is an independent deterministic gzip stream, with mtime zero, no filename,
level 9, and size at most 65,536 bytes. refresh-manifest.json records SHA256, Git blob SHA1,
uncompressed hashes and successful byte roundtrips.

refs-delta.json.gz plus the exact original captured-refs payload reconstructs the new
captured snapshot. Verify the before SHA, replace that one name, and serialize with
json.dumps(value, indent=2, sort_keys=True) plus newline. The manifest records both hashes.
graph-delta.json.gz appends its new_parent_rows to the original full parent graph.
The native job checked every actual Git parent row against the original graph plus that
single new row, found zero missing parents and rechecked every original coverage-map hash.

observed-protection-505.json.gz preserves all 504 production pins, adds the exact new
commit, and advances the recorded protected name. This is a new observation artifact;
it does not alter the 504-pin production manifest. Current protected names remain 483.
Coverage and HIA intersections were rechecked using complete local commit history,
with implicit fetch disabled. Any later remote movement is separately recorded in
refresh-result.json and was not chased.

The original full-history export is identified by its manifest SHA256 in the delta
manifest. The refresh contains no duplicated full graph or full ref payload.
