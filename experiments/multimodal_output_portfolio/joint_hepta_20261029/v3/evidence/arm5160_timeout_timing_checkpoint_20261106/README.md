# ARM timeout and timing-source checkpoint

This packet preserves both original diagnostic ZIPs from ARM run 42302971192,
job 128186230225, at source 45c086c60685db6fb5aff82b3f9d75227be35d40.
It also preserves the original job log and API responses, exact source bindings,
owner and root audits, and the later single-file timing source published as
PR 5188. The new source has no native result in this frozen packet.

The original build completed both nextest list commands and retained its
built_not_executed status, clean source, and unchanged dependency seed. The
business run then executed one case: zero passed, one timed out after 1200.063
seconds, zero were ignored, and eight other cases were filtered. The original
just command exited 100. Its last stage was agent_pair_ready:done; the next
first_encrypted_turn:start marker was not observed. The old secret-capability
newline failure was passed on this path. The overall business result remains a
failure.

The two official ZIPs contain all four original ZIP members, the complete
1,447-file diagnostic view (68,372,540 bytes), and the 84,421-entry native source
catalogue. Their official byte identities, CRCs, every selected payload identity,
and every catalogue classification were checked. The original collector limits
remain 5,000 files, 1,024 path bytes, and eight parts of 128 MiB. The tar payload
mode is 0600. Outer packet restoration is deliberately inert mode 0644; original
outer-file modes are recorded in INDEX.

The complete 1.79 GB original ARM artifact was not downloaded, independently
hashed or reconstructed. Its official artifact ID and digest are retained.
Excluded cache and other-suffix entries have catalogue metadata only. Complete
projection means the declared selection, not the whole original artifact.
The expanded copies of selected files are not duplicated in this outer packet;
they can be read from the retained original ZIPs. The prepared native worktree
commit and workflow merge are distinct commits with the same exact source tree.

## Why the new source only observes

The failed log cannot distinguish repeated release-file hashing from the two
Matrix sync calls or the two later idle-ready checks. Repeated hashing is a
hypothesis; aggregate child CPU cannot prove its location. PR 5188 adds fixed
start/done observations for exactly five hash labels and six post-ready
operations. It retains one original read and validation call, returns the same
Result, and keeps every operation, argument, assertion and await in order.
Only fixed labels, elapsed monotonic milliseconds and file byte counts are
added to output. No path, data, digest, error or environment value is printed.
HASH_DONE means the validator returned, including an error Result. Logging has
observation overhead and is not a performance fix.

Root verified the whole-file reversible observation delta and ran the original
just fmt. No timeout, retry, test selection, fixture, dependency, source seal,
or security policy was weakened. A new original native run is still required
to localize the time and qualify any later repair. Initial local formatting and
audit path-shape failures are preserved alongside their corrections.

## Restore

Run python restore.py /absolute/new/destination. The unchanged reviewed reader
verifies the fixed INDEX, all compressed parts, the complete tar and every file
before writing regular inert files with mode 0644. It never executes archived
sources. The original byte identities and original modes are in INDEX. Any
intentional replay of an auditor should use another directory and preserve the
original receipts. The previous failure and pending new qualification remain
separate.
