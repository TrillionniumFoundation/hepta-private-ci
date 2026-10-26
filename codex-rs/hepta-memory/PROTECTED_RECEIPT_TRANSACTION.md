# Protected receipt transaction

`ProtectedCognitiveCheckpoint` has one asynchronous mutex for its original
protected receipt. `ProtectedReceiptTransaction` privately owns that same guard
across each complete bounded authenticated protocol. Initial verification,
Current-to-Dirty checkout and Dirty-to-Publishing-to-Current acknowledgement
retain their original serialization and gate transitions. Another checkout
cannot race the expected token while a remote CAS is awaiting its reply.

This domain transaction exposes no general lock, receipt mutation or grant API.
The generic workspace async-lock lint remains enabled without exemptions.
Moving the guard into the transaction does not replace it with a cached copy,
release it before publication, change an expected token or allow dirty commits
before the original acknowledgement.

`observed_current_receipt().await` is a read-only operation in that same
transaction. It first requires the retained head to be Current with no proposal,
reads the original fixed authenticated transport through `read_head`, and
requires the complete returned token/head to equal the original receipt and
remain Current with no proposal. It returns the actual transport response.
Dirty, Publishing, Fenced, malformed or changed responses are refused without
updating the cache, publishing a cut, opening a commit gate or creating authority.

A Current receipt is evidence of its named original cut at that observation.
It does not authorize another write, substitute for a live lease, establish a
power-loss guarantee or qualify a different kernel/device. The native product
must bind its own exact source, original owner, authenticated peer and receipt.

The original protected-checkpoint test group covers whole-owner SQLite writer
exclusion, failed and lost replies, cancellation, receipt retirement and
revocation. The fresh-observation tests also count actual `ReadHead` calls,
check anchor/peer/gate immutability, reject Dirty without I/O, and reject an
actual changed peer head without adopting it. These use explicit protocol peers;
they are not an independent Root-host or physical durability qualification.
