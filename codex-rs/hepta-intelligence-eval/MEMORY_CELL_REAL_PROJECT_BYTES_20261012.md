# Independent public project source extension: actual Git-object byte gate

The six new project-family proxy PR heads in the source-only extension must
not be admitted for any memory/reader experiment based only on GitHub PR
metadata, head SHA strings, or an unreviewed natural-language question.

The bounded project_pr_family_bytes.py command uses **only** the six sealed
repository names and their immutable Git commit/tree/blob object IDs. It checks
every original PR commit's timestamp and contiguous ancestry, exact HEAD
tree/parent tuple, tree paths and file modes, and decoded Git blob bytes
against Git's blob SHA-1. A second disk read checks SHA-1 and SHA-256 again.
No READY is emitted on a partial or modified cohort. The source manifest's
declared 14 commits and 32 original file refs cannot be resized.

Source authority is deliberately narrow: GitHub's API supplies commit and
tree metadata and the decoded original file bytes. A Git commit ID is not a
separately authenticated historical PR discussion, and its returned dates
do not prove an externally certified prior observation window. The original
blob byte check proves exact byte identity only for the six frozen PR heads.

The read-only scoped Actions workflow
.github/workflows/hepta-memory-project-family-bytes.yml exercises these
checks against the real public Git API. It retains only audit, identity and
hash receipts as artifacts. Original third-party source bytes are staged
ephemerally, **not redistributed** in this repo's Actions artifact. A later
reader must re-acquire and verify the same pinned blobs under its own proper
data-handling policy. No model weights or test answers are involved.

Even if original file bytes pass, parent changes must still be independently
bound and source sufficiency/answer/citation entailment must be reviewed
before building a blinded QA target set. The ten distinct project names
(including the original four) are only source-family **proxies**. They are not
ten statistically independent human-reviewed observations and cannot satisfy
the N>=200 production floor or the real future-window requirement.

This work does not change production Rust owners, active adapters, the strong
RAG baseline, historical negative comparisons or the independent citation
qualification threshold.
