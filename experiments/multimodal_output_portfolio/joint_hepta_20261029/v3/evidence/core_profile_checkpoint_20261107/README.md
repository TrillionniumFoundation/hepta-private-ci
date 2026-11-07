# Core35 terminal evidence after the same-job profile prerequisite

The original seven Core cases each executed once and passed in PR 5267,
run 42351036047, attempt 1, job 128339012777. The exact source head is
a84d999843fdece0f950c47d5d5c016dd0f9581a. The complete prerequisite
mechanism passed in this same job before Core execution.

The overall workflow and the complete nineteen-slot Core evidence gate
remain FAIL. The unchanged scanner accepted eighteen originals and rejected
logs/list.stderr.log with URI_UNRECOGNIZED_FRAGMENT. The rejected stream is
absent from the official artifact. Only its original manifest identity and
rejection code are preserved; its bytes were never fetched, reconstructed,
read or packaged by this review. Accepted evidence cannot identify the
offending URI or fragment. There is no scanner exception or rewritten log.

Both official ZIPs are preserved unchanged: Core artifact 13565649343 has
nineteen members (manifest plus eighteen accepted originals), and profile
artifact 13565457834 has 147 members (manifest plus all 146 originals).
Their accepted originals are also included byte for byte with exact ZIP
member provenance in INDEX. No private administrative console is included.

The accepted runtime output and JUnit agree on seven actual passes with
one attempt per case, zero ignored cases, and no test-internal macro skip.
The nextest summary's 1380 skipped tests are selection filtering. Repeated
PASS display lines do not add samples. Parent run.stdout is empty; captured
child stdout appears in the original run.stderr success-output sections.

The full 146-slot profile mechanism has all six original checks passing,
31 exact command records and 72 fixed reads. The same-directory repair
changes mode 0777 to 0755 while preserving the measured default ACL. The
post-setup child reports the exact enforced profile stack, zero permitted
and effective capabilities, distinct namespaces and working loopback.
This is evidence for this VM, not earlier VMs or a full product suite.
Historical subtree trust, interpreter dependency closure and VM teardown
remain outside the proof. The baseline PID relationship is source-inferred.

The peer review independently checks fresh source/API identities, eleven
complete Git trees, seventeen product pins, all accepted bytes, original
arguments, direct child summaries and JUnit. Only selected pure validators
were replayed on captured data; no native work or host operation was rerun.
Root independently reviews these findings and the raw accepted evidence.

The initial peer auxiliary matcher failure is retained. It omitted the
four-space indentation of nextest success-output summaries; audit_v2.py
changes only that matcher. Original pure checks already accepted those
bytes. Initial and corrected reviewers, outputs and the exact delta are
preserved. Earlier queued observations and source manifests retain their
original pending statements; later receipts do not overwrite them.

Restore to a new destination with:

    python -O -B restore.py /absolute/new/destination

The qualified reader differs only in its fixed INDEX seal. It checks all
members and bytes, executes no embedded source, and restores inert regular
0644 files. Original stat and permission modes are recorded in INDEX. Each
transport part is a valid gzip container no larger than 450000 bytes.
One in-memory roundtrip verifies the exact set, bytes and recorded modes.
