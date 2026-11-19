# Fresh branch protection before the Darwin source update

The remote snapshot was observed on 2026-11-16 at 18:09:40 UTC. It contains 7,318 branch heads, including 87 protected HIA heads. Main and the integration branch still match the expected original and published commits.

Compared with the independent 17:19 snapshot, no branch appeared or disappeared. Only the HIA union branch advanced. Its new head descends from its previously protected head and the protected HIA marker. The complete names, old and new commits, protected vector, and original reference bytes are preserved in the evidence.

The examined unpublished candidate is 3d6d17adfa92757085a371d67cd269e043d8dbed. Its sole parent is d8b24300d190bef3d3c9d94765b256412e3fb867. Its exact commit bytes and tree identity were checked. Neither HIA marker nor any of the 87 observed protected heads is in its ancestry.

The original eligible inventory contains 7,230 heads. This candidate retains 1,796 through their original Git parent histories; 5,434 remain pending. The complete retained and pending vectors are included. These are ancestry counts, not a claim that pending changes have already been reviewed.

## Exact graph scope

The observed remote heads reach 76,867 commits and 81,344 parent edges. The augmented analysis graph reaches 76,878 commits and 81,358 parent edges. Its 11 additional commits belong only to the unpublished candidate ancestry. They are explicitly listed and are not counted as published branches.

The exact walk roots for both graphs are in the original snapshot. The complete augmented parent map is preserved as ordered lossless gzip parts. An independent traversal of that map from the remote roots reproduces the observed remote commit set and every parent row. The comparison receipt records a canonical digest for that closure as well as the original walk digest.

## Preservation and limits

The 17:19 snapshot remains unchanged. This package appends a new observation and preserves all original raw bytes listed in its manifest. Every compressed artifact is at most 500,000 bytes. The original repository size policy, format rules, and spelling rules remain unchanged.

Read the manifest to verify compressed and original identities and to reconstruct the parent map. Restoration requires no execution of archived programs. This audit changed no remote refs. A later publication still requires the expected integration reference to match, while HIA work is allowed to continue independently.
