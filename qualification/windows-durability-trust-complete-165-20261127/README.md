# Four complete Windows durability and trust targets

Exact source 165516b637fff71cddbbf62295c0bf7c70c09a05 completed the unique
run 46040504856 / job 140646717244 successfully. The evidence-only parent 5766
has identical product and workflow bytes to the tested source.

The original terminal-cell owner target passed in 0.5 seconds, full contracts
unit target in 107.2 seconds, full operator acceptance target in 2.7 seconds,
and full shadow qualification target in 0.6 seconds. The original uncached
command ran all four targets and independently required their exact PASSED
summaries; the full raw log contains no actual failure, retry, or FLAKY result.

This closes the directory handle/flush, held-owner fixture, and pinned
Windows SSHSIG/OpenSSH ProgramData changes for these targets. The earlier
complete Windows failure and all earlier native format/test evidence remain
in their ancestor commits. All original assertions and target bounds remain.

The original 3,645,011-byte Actions ZIP has the published SHA-256 and valid
CRC for both complete members. Every member was reread and hashed; the complete
raw job log is separately preserved with its exact digest. This is a four-target
qualification and does not claim that the full original Bazel matrix passed.
