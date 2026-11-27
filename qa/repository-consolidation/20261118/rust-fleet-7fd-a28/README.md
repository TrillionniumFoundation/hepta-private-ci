# Original Fleet strict fixture history

Ordinary branch `fix/shared-encoder-fleet-strict-clippy-20261018`, tip
`7fd4b93c6fd917ad5e07115a6b2a929ea62b8964`, contributes exactly one previously
unmerged commit. Its complete net change is one authority fixture file.

The incoming source blob is exactly the authority postimage independently
reviewed in rust-fleet-a28. Four real ancestor commits retain that full
postimage, and the subsequent evolution to the current fixture was reviewed.
Every setup failure still fails its test; the exact revoked-lease rejection,
all receipt and witness fields, scope inequality and payload equality remain.
Current verified-clock production behavior and its regression module remain.

The agent performed an ordinary merge with five actual conflict blocks and
six automatic Result-style fragments. Each was resolved explicitly; the
resulting complete tree equals the current source tree. Root independently
read the full patch, verified all three input blobs, and repeated the real
merge on the assembled AuthBus, Fleet, learning and historical-evidence
parent. Its entire tree stayed unchanged at
`58795ab96fd7d582f6a313607512014a09b7a358`.

The archive retains 39 original regular files, including the full patches,
source snapshots, conflict decisions, actual merge state, a verified Git
bundle, historical witnesses and the latest 368-reference HIA proof. Every
member size and SHA-256 was checked again. No native or formatting command
was repeated for this zero-source-change merge, and no new platform or
Clippy pass is claimed by this history review.
