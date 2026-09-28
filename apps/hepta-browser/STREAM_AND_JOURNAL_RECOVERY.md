# Agentd stream retirement and verified-prefix journal reduction

This extends the existing Browser service and V1 operation journal. It adds no
executor, authority issuer, journal format, global state store or effect retry
path. The worker-side lifecycle is described separately in `WORKER_RECOVERY.md`.

## Agentd channel lifetime

`AgentdBrowserChannel` permanently fences admission on input close or output
close/finish, even when no error event is emitted. Already destroyed/closed/ended
stream flags are checked at construction and actual use, because stream teardown
can precede delivery of its close event. Pending writes and reads reject; late
write callbacks cannot undo the fence. EOF drops queued but unconsumed requests
and does not acknowledge pending output writes. A clean idle EOF remains clean.

`ParentFinalUseAuthority` retains its existing request-scoped checks before and
after receiving authority and immediately before and after invoking its consumer.
A closure cannot release a retained or queued authority-enter callback. Closure
after consumer entry does not prove non-execution: it prevents a response or
boundary frame and leaves the external outcome to the existing durable owner.
Do not retry an effect merely because its transport is closed.

`BrowserAgentdService.run()` may finish quietly when a typed channel retirement
is observed while idle awaiting its next request. This produces no result frame
and certifies neither an effect outcome nor child/resource retirement. Errors
during an active service exchange still reject; malformed protocol input is not
converted into a normal service completion.

The private worker pipe client now applies the same close/finish and synchronous
retired-stream checks at construction, request admission, write callback and
reply delivery. A diagnostic-only pipe closing does not itself prove a transport
failure. Worker signalling remains best effort; its unchanged process owner must
still observe actual child exit and pipe closure before releasing the profile.

## Journal reduction index, not cached authority

`FileBrowserOperationJournal` retains the immutable latest record per operation
for its already verified live prefix. Every public read or write still opens the
file and performs the complete bounded read, canonical path, private permissions,
inode/device, size and prefix-digest checks. There is no timestamp-only shortcut.
Only complete new suffix frames need JSON decoding, checksum verification and
semantic reduction. A temporary changed-key map handles multiple transitions for
the same operation and publishes nothing until the entire suffix validates.

A locally appended result enters the index only after the file and directory sync
barriers, exact post-write observation and successful close. Possible I/O failure
poisons the handle and all queued operations. A failed handle cannot return its
old cached answer or be repaired by restoring bytes underneath it. A semantic
rejection before I/O does not poison unrelated valid operations.

The queue accepts at most **64 active plus queued operations per file handle**.
An excess call rejects before joining the queue; its capacity error does not
cancel or acknowledge already admitted work. Completion or rejection returns the
slot. This bound does not authorize replay of a previous operation. Callers must
retain the existing operation ID and use the normal owner reconciliation path.

The on-disk V1 format, 64 MiB file limit and 262,144-byte line limit are unchanged.
The index is reconstructed after reopening and is never serialized separately.
Prefix-preserving external appends remain readable, but this is not authorization
for concurrent writers. The existing exact-predecessor write check still rejects
concurrent growth between reduction and append.

## Verification

Run through the existing Browser test entry point:

```sh
node --test apps/hepta-browser/test/*.test.js
```

Focused scopes are `test/agentd*.test.js` and `test/journal*.test.js`. New stream
cases include actual Node stream destruction, missing write callbacks, queued
final-use entry, closure after consumer entry, already retired streams and idle
EOF. New journal cases count actual JSON parses and actual disk bytes: repeated
lookups must not reparse old history but must still read every current byte.
They also cover external suffixes, staged transitions, malformed suffix tails,
checksummed regression/prefix mutation, immutable reopen and bounded queue reuse.
The existing sync, path, rollback, identity and monotonicity tests remain intact.

Developer observations for this continuation (Node 22.16.0, Linux): 13 new stream
cases include 12 failures on the old source; 10 new journal cases include four
old-source failures. The remaining cases preserve already-working behavior.
Final scoped execution passed 45 Agentd and 67 journal tests. These sets overlap
with the complete Browser suite; they must not be summed as independent coverage.
These are developer test observations, not production activation or independent
acceptance. The final source/fixed-main merge workflows remain necessary.

The corresponding worker closure slice adds 12 cases, including ten failures on
the old worker client. After synchronizing the complete current Browser sources
and tests, the full Browser JavaScript suite passes **228 tests, zero failures,
zero skipped** (193 existing plus 35 new). This supersedes the earlier supplemental
179-test run on historical unrelated Browser files. It still does not establish
Rust/native compilation, exact-source/fixed-base merge execution, a real Servo
user task or full A-E completion. Source-tree and command/log identities belong
in the delivery evidence and PR, not in an automatically advanced completion flag.

## Capacity and recovery limits

The change removes repeated parsing and full-map reconstruction, not the cost of
reading/hashing history. Startup and explicit reopen still replay the entire
bounded file. Listing still visits the in-memory operation index. Local 128/512
operation samples showed faster hot reads, but variable ingestion and slower
reopen; no target-host throughput, tail-latency or multi-day SLO is established.

There is still no cross-process kernel writer lock, independently witnessed
anti-rollback frontier, generation compaction, multi-owner migration or power-loss
qualification here. Preserve the journal and unresolved operations after failure;
recover with the existing owner rather than truncating, replacing, or silently
creating a fresh file. Stateful organ add/split/merge/retire still needs durable
writer/state/parameter handoff and independent terminal/resource observation.
