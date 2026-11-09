# Supplementary metadata completeness correction

The predecessor evidence commit is
`a9116a22d4cc429e9b34a1327bcb3945280d72d4`, tree
`cc2aabdda8e465e88279b858e940ce62dd83273f`. Its normal push and exact remote
commit/tree/parent readback succeeded. A later independent committed-object
readback nevertheless found that one declared supplementary observation was
not in that commit. The original success receipt and failed independent
readback are both preserved; the former is not proof of all metadata bytes.

The omitted file is exactly
`observations/evidence-addendum-increment-006a/VERIFY.log`, 6,186 bytes,
SHA256 `176aa75a9743028dc3d158b52d1a4fdb3fdd0a26bba8eed530eb25cac8a677a2`.
It matched its approved local bytes but was excluded by the repository's
existing `.gitignore:47:*.log` rule. The other fourteen observations were
present in the predecessor with the correct bytes. The old publisher checked
the working tree, but did not verify every observation's staged and committed
Git object. This correction retains that failure and adds the original file.

The original receipt reported `published_file_count: 1140`. Direct listing of
the predecessor's committed evidence subtree contains **1,139 files**.
The unchanged local directory contains 1,140 files, and the unique difference
is the omitted verifier log. The root manifest has no published-file-count
field: its **81 packets and 9,136 archive-member entries with overlap** are
different counts and remain unchanged. COUNT_AUDIT.json and the original Git
tree listing preserve both count bases without rewriting the old receipt.

This additive correction changes no existing packet, root manifest, root
README, prior metadata document, original fourteen observation bytes, source
commit, or test result. It uses `git add -f` only for the exact approved log
path; it does not modify ignore rules, amend history or force-push. New files
are limited to the retained readback/closure originals, this explanation,
the preparation inventory and publisher, a pinned input manifest, and the
actual index-closure audit.

Every added byte is checked in the Git index before commit and in the new
commit before its one normal push. The original fifteen observations are
checked as a complete set at both boundaries. The remote commit/tree/parent
must match after the push. INDEX_CLOSURE.json is emitted only after actual
index checks; its own bytes are subsequently checked too. The publication
receipt is external to the commit it verifies and records the final new
identity. Source and original failure records remain unchanged.

The two readback and diagnosis directories are retained in full within their
declared scope. The original publisher contribution is limited to its RESULT
and commands index; its remaining outputs stay in its original record prefix.
No native test, CI rerun, build, new learning, adoption, or successor
consumption occurs in this correction. Full physical and historical costs
remain null. S0, S1, S2, S3, S4 and S5 remain HOLD.
