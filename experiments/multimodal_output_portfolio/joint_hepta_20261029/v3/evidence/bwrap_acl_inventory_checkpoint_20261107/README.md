# AppArmor ACL inventory evidence

This additive checkpoint preserves ACL32 source, review1/review2/review3,
the descriptor-custody and EXITED/errno counterexamples and their corrections,
pure decoder/report checks, A/B/C bindings, independent peer and root reviews,
and both original automatic entry outcomes. Previous 28/29/31 packages remain
unchanged. No later AppArmor33 proposal or result is included.

The first entry, PR #5245, used a branch name that did not match the frozen
source contract. Run 42339995217, attempt 1, failed in preflight; its dedicated
helper, observation, collector and artifact upload were not reached. The exact
internal error string was not printed. Root then created the correct branch and
PR #5247 using the same commit and tree, with the same strict #5244 parent.
The old PR, failed run and initial snapshots were not deleted or rerun.

The corrected entry's run 42340339734, attempt 1, job 128306389981 succeeded.
Its exact official 8,318-byte ZIP has nine CRC-valid members: the manifest and
all eight accepted originals, with no missing or rejected slots. The root and
owner independently checked original bytes, source identities and the finite
report. This is complete read-only observation evidence, not AppArmor mechanism
success, product qualification, or P0 closure.

In that new VM, both captures reported / and /usr as root-owned mode 0755,
and /usr/share as root-owned mode 0777. The access/default ACLs for the first two
directories and the access ACL for /usr/share were absent. Its default ACL was
version 2, 44 bytes, with five entries: owner, named user 1001, group, mask, other;
all permissions were 7. Both captures were equal and all three held descriptors
were explicitly closed. This observer did not measure the unprivileged caller's
UID, change a directory, run a namespace or parser, or load a profile. It does
not establish historical subtree integrity or an atomic directory history.
The new VM facts do not fill gaps in the earlier AppArmor31 failure.

The original helper descriptor-custody gap remains recorded against review1.
The corrected helper uses three preallocated slots. The old report validator's
acceptance of EXITED with errno 5, the root counterexample, the peer's initial
miss, and the later exact refusal are all retained. Root audit-script and path
lookup errors are also preserved separately from native execution. The final
root terminal directory contributes four regular files, including two initial
lookup-failure records. Publication and entry-recovery journals are included.

Only identities of the two private administrative consoles are retained in
INDEX; their contents and temporary signed download URLs are excluded. No
rejected stream is reconstructed. This checkpoint records prior package
references where an audit reused earlier inputs; it is not a host replay kit.

Restore to a destination that does not already exist with:

    python -O -B restore.py /absolute/new/destination

The previously qualified reader differs only in its fixed INDEX seal. It
checks exact members and bytes, restores inert regular 0644 files, executes
no embedded source, and writes nothing into this package. Original permission
and stat modes are recorded in INDEX. Each transport part is an independently
valid gzip container no larger than 450,000 bytes. The owner performed the
reader's sealed in-memory roundtrip without a second on-disk extraction.
