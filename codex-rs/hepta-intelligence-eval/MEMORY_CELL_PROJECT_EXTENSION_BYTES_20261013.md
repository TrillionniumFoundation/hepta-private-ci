# Six real-project source families: original immutable Git bytes (Oct 13, 2026)

**Research source-integrity acquisition only. No model inference, answer labels,
independent human semantic adjudication, training or production admission.**

The earlier precommitted six-project cohort, at source cutoff
`2026-10-12T16:05:00Z`, registers **six distinct repository names, 14 Git commit
IDs and 32 HEAD-file path/blob identities**. Its source manifest Git blob SHA-1
is `5c7ba1b6dd4cafb445794346afb21687816f726e`, and the original earlier
four-project source cut has exact SHA-256
`ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463`.
These registered cases are retrospective public PRs, **not an authenticated
independent effective N of six**, prospective source windows or independent
reviewers. Original manifest fields remain frozen and must not be rewritten to
claim a review or successful download.

## Direct exact-source verification from GitHub connectors

The first independent API-based source inspection checked **31 of 32** original
files by separately recalculating canonical Git blob SHA-1 from the returned
original UTF-8 bytes and matching the API-returned SHA to the precommitted
file SHA. All **14/14 original commit objects** were reopened, including **6/6
HEAD tree, parent and committer-date bindings**. Source byte counts for these
31 files were measured. The one remaining file is
`denoland/deno` `tests/testdata/encoding/iso-8859-1.ts` (expected Git blob
`a772b57bdd5aa26fbedd07cb057b9006239e784e`): the API-returned identity
matches, but its Latin-1 byte `0xe9` cannot be recovered from the connected
UTF-8-text-only file interface. Re-encoding the returned replacement character
changes the calculated hash. **This is a byte-boundary blocker, not a source
mismatch or a model failure. Do not claim 32/32 from this inspection.**

## Byte-exact model-free acquisition gate

`project_pr_extension_source_bytes.py` uses exclusively allowlisted, SHA-pinned
Git commit/tree/blob REST object endpoints. It validates all six HEAD tree and
parent links, all 14 commit identities/dates and every path by walking the
**original Git tree**. Crucially, it reads immutable Git **Base64 blob bytes**,
not decoded UTF-8 text, and verifies both the original Git blob SHA-1 and a
fresh raw-byte SHA-256. The Latin-1 file is retained exactly like any other
blob. It caps each file at 1 MiB, the complete corpus at 16 MiB, immutable
requests at 256 and source JSON responses separately.

Only a complete 6/14/32 source census writes immutable `inventory.json` and
`READY.json`. Partial failures publish `INCOMPLETE.json` without READY. An
entirely separate `reopen` process rechecks all physical original blob bytes,
exact path and source partitions, canonical receipt data, Git SHA and SHA-256,
including the non-UTF-8 census. The workflow performs the complete acquisition
and a second **separately hosted independent reopen**, each recording its exact
code commit and SHA256SUMS manifest. No source file is executed as a command,
and no proposed benchmark answers, targets, model weights or training data are
created.

Eight local model-free regression tests passed, including full synthetic
6/14/32 byte and commit roundtrip, Latin-1 preservation, changed-source and
Git-tree rejection, changed parent/cut refusal, duplicate JSON rejection,
overwrite refusal and disallowed repository endpoints. Synthetic fixtures do
not substitute for the actual original public Git objects. The GitHub workflow
must conclude successfully and its artifacts must be audited before the 32/32
original-source-byte gate can be marked passed.

## Only then: independently judged tasks

A valid source-byte receipt does not establish a PR's complete historical base
diff, historical review discussion, permission for additional private sources,
or sufficient evidence for any generated answer. The next experiment requires
actual independently authorized and blinded human reviewers to freeze
source-sufficient tasks on these byte-bound projects, then the same strong
reader/tools/budget controls (calibrated lexical RAG, single-hop, full path,
correction-aware organizer and frozen learned/parametric-only candidates).
No benchmark answer label may enter the reader or selection policy before all
reader outputs are durable. Report cluster-level uncertainty, complete
citations, failure denominators and real retention/revocation/recovery costs.
`independent_semantic_review=false`, `production_accepted=false` and
`parametric_memory_training_qualified=false` remain mandatory.

## Completed byte-exact GitHub Actions closure (independently checked, 13 October 2026)

The source-only gate **did subsequently complete**. [Actions #38320847158](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38320847158), generating source `6ac55532cd3f65d02438cda7f642dc22afb107fe`, has two successful jobs: `exact-git-source` and separately executed `independent-reopen`. This does not erase the earlier 31/32 UTF-8-interface failure: the completed gate read original Base64 Git blob bytes rather than replacing the Latin-1 byte.

- Original source ZIP artifact `11778273351`, outer SHA-256 `a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4`; all **40/40** internal SHA256SUMS members rechecked.
- Independent reopen ZIP artifact `11779107585`, outer SHA-256 `59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36`; both **2/2** internal members rechecked.
- Exact inventory SHA-256 `5ede9326e2234331f8f7f268a96257089a6703a74e7354206833db1d18f1beb0`. Independently recalculated all **32/32 original Git blob SHA-1 hashes**, plus per-file raw SHA-256 and lengths, for **1,558,460 source bytes** across six public project proxies and 14 source Git commit objects.
- One non-UTF-8 original source blob, `a772b57bdd5aa26fbedd07cb057b9006239e784e`, was retained byte for byte. The separate process reports `original_binary_reopen_completed=true`; its recorded file/byte/commit totals match the original archive.
- The original acquisition's `READY.json` deliberately had `all_original_binary_bytes_reopened=false`, since the separately hosted reopen had not yet occurred at that stage. Treating the later independently recorded completion as a separate gate preserves chronology.

The machine-readable, no-answer receipt is [`six-project-independent-byte-closure-20261013.json`](../../scripts/memory_cell/data/six-project-independent-byte-closure-20261013.json). An independently written read-only ZIP/Git-hash verifier was also run against both downloaded Actions artifacts; all five focused local tests passed. Source-byte verification does not authenticate the original full review discussion, prospective independence, external human sufficiency reviewers, benchmark answers or an actual Reader result on these projects.

**Next hard gate:** restrict reviewer access, externally register point-in-time source-grounded tasks/answers, obtain authenticated independent sufficiency and citation judgments, and only then run the exact same frozen Reader/RAG/full-path/organizer budgets across disjoint held-out project families. `independent_semantic_review=false`, `parametric_memory_training_qualified=false`, and `production_accepted=false` remain mandatory.
