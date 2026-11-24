# Second Rust consolidation checkpoint

The candidate gained the full history of `codex/windows-ci-base-20261026` at
`5336c712d9ed3511fbccc35fe078fed848763e33`. Its two parents are
`f09fd47783d0897f06b4fe0a1df4fe7207c32ae2` and
`641641c2b6b8d7ce23fbdfc61f76b6cced4949bc`. The merge reconciled six
metadata conflicts. Each of the ten original changes matches a reachable
commit across every path, file mode and Git object ID. A single reachable
successor matches 97 of 98 touched paths byte for byte, including all 76
Rust files. Its caller manifest includes the original values for all 45
boundaries and 30 protected files.

The [machine-readable proof](windows-ci-history.json.gz) contains the original
and counterpart parent IDs, raw tree deltas, six resolved blobs and candidate
tree. Its SHA-256 is `0f1a931f54b644e9a52ef4cc77ee9c7e07ddddd31162c207a3e50b2297ce1cce`.

The second two-parent merge `c532d3b5a58d6cc48891382c5e8a26cdabd104c5`
preserves the 53 original commits of `codex/learn-prefix-publication-20261112-ff41`.
All 53 changes match complete raw Git deltas in the existing candidate history.
Replaying the 93 first-parent steps through the common successor accounts for
all 202 authored paths, including the 35 subsequently edited by intervening commits.
The next 1,066 first-parent steps explain the current state of all 202 paths.
Of the 68 paths requiring reconciliation, four were unchanged since the common
successor and 64 have a verified later edit. The current mutable journal
receiver is retained. The [detailed Git proof](prefix-publication-history.json.gz)
has SHA-256 `8f3dde523dac1327eb9aa33cf9b69b188e01b476b56232ce8e03275de65b4f98`.

The live snapshot had 8,102 branches, of which 608 were protected as HIA.
The two new merges cover 2,932 of 7,493 ordinary heads. The remaining 4,561
ordinary heads are outside this candidate. The observed main head
`732e934ba496d90fbe042b8d41d479ef901643e5` covers zero ordinary heads.
Three earlier merged PRs, [#1000](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1000),
[#1279](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1279) and
[#1310](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1310),
have branch trees identical to their squash commits in main. The original
branch tips remain outside main's parent graph and were retained.
Refer to [the original inventory](README.md) for its scope and the earlier seven merges.

## Required whitespace check

The storage repair at `4c58aea55213a62d683c9ac6ecd52274cdfe60f5` used
the existing archive readers and retained the source manifests and original
bytes. The comparison used the live main and the candidate, with the same
Git attributes used by the check.

| Original paths | Before | After | Verified original payloads |
| --- | ---: | ---: | --- |
| source84 CI evidence | 31,343 | 0 | 9 logs, 6,134,932 bytes, plus 9 sidecars |
| source0a5 CI evidence | 23,974 | 0 | 12 logs, 8,072,868 bytes, plus original readback records |
| H4 paired-row exports | 15,362 | 0 | 2,775,720-byte CSV and 1,850,445-byte exact prefix |

The three scopes removed 70,679 diagnostics across 63 paths. The incremental
Git whitespace check passed for every changed path. Other paths continue to
require review. The ten combined raw-evidence controls passed, including
a complete restoration of 188 registered original paths. The seven legacy
library recovery outputs and both neuroscience records also matched their
original bytes. The H4 reader passed eleven previous tests and four new
controls covering original hashes, truncated or modified archives, extra
gzip members and restoration from both manifest versions.
