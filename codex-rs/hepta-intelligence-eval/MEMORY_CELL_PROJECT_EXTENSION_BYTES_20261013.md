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
