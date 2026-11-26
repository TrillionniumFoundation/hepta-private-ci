# Consumer for three parent-descriptor memory checks

This layer adds a consumer for the frozen test-only `PARENT_SD_PROTOCOL.md`
observation. It changes no Rust source, token, ACL, original test assertion,
workflow trigger, native command, timeout, retry or test selector. A complete
observation cannot qualify production filesystem confinement or repair either
original failing case.

## Source and execution binding

The existing recursive `SOURCES` inventory already covers the complete sandbox
crate and this qualification directory. Its tuple is unchanged. The explicit
`OBSERVER_BLOBS` map now binds the recovered observer, new memory-only helper and
its protocol to their exact Git blobs. All previous unrelated pins remain.
The frozen recovery source commit has a new identity after local state loss;
matching source bytes and tree do not claim recovery of the old commit object.

The original eight commands, two exact native tests, one test thread, zero
retries and 20-minute job budget are unchanged. So are the original nextest
configuration, enumeration and excluded-count checks, before/after executable
identity and before/after source snapshots. The old native, child-token and list
verifiers remain byte-identical. The new consumer runs after the existing
child-token and fixture/support consumers and before the original native-log
verifier, without executing any additional command.

## Complete observations and refusal

Exactly one `HEPTA_PARENT_DELETE_CHILD` JSON line is required before the actual
nextest summary. The consumer enforces its original 4096-byte prefix-plus-newline
limit, rejects duplicate JSON keys and requires exact object fields. All three
ordered variants must be present: original copy, restricting-capability deny,
and actual-user deny. Requested access is exactly 64. Each API must succeed;
every allowed result grants exactly 64 and every denial grants zero. Successful
access has no error field value; a denial preserves its raw unsigned error value
without assuming a particular error number. API failure is never a denial.

The original-copy control must allow and the actual-user control must deny.
The capability row may allow or deny. Every recorded memory, captured-token,
component-preservation and control comparison must be true, with the exact
selected capability index, restricting-only status and two-capability count.
Typed sizes and numeric values remain bounded. Any unknown, missing, duplicate,
truncated, reordered or contradictory record remains an incomplete observation.

The new record must occur in the same captured stream after the original seven
before-phase records and before the original eight remaining records. The
consumer binds it to the existing before-token and parent-access anchors.
It does not invent an inter-stream ordering. Summary recaps are excluded from
attempt counting. The old verifier still owns the complete original 15-record
contract; redacted summaries cannot independently reconstruct raw SID equality,
full descriptor bytes, atomic token custody or kernel deletion behavior.

The added receipt reports `production_confinement_qualified: false` for every
outcome. A usable capability denial is labeled only as blocking this one
`AccessCheck`. Missing or invalid observations append an error while preserving
the original native and strict-Clippy exit codes; the controller continues to
return its first nonzero command exit. A completed observation never converts
the original test failures into passes.

## Local verification boundary

The companion Python controls exercise accepted capability allow/deny outcomes,
API-error versus denial, grant/control consistency, strict types and schemas,
output bounds, ordering, original-record anchors and unchanged failed-command
receipts. They use synthetic records and no Windows APIs or native processes.
Historical native logs remain evidence for their original source only. A missing
new record in those logs is unknown, not a retrospective observation. This source
and consumer require separate review before one normal native workflow may run.
