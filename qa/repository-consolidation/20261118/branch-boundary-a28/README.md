# Refreshed ordinary and protected branch boundary

## Latest snapshot: 15:56:37 UTC

The later exact snapshot contains **7,593 branches: 7,224 ordinary, 368
protected HIA, and main**. Both newly added names belong to HIA, including
`dot/isolate-lost-reply-test-timeout`. The moved
`dot/upgrade-rmcp-3-9-advisories` name was already protected and stays protected.
Three protected references advanced externally; one ordinary owner reference
advanced and remains pending review.

The compact incremental archive preserves all eighteen immutable comparisons
against the two HIA roots and anchor, the complete nine-node new parent
closure, exact protected inventory, and a lossless compressed ref snapshot.
Root independently verifies every archive member, the restored snapshot,
all 368 protected tips, and the complete assembled ordinary history graph.
There are no missing graph parents or protected intersections. This batch
covers **2,070 ordinary names**, leaving **5,154** outside its ancestry.

No protected ref was written. Main remains unchanged and no branch deletion
is eligible from this snapshot. These are recorded snapshot facts; eventual
cleanup still requires fresh exact refs and reachability from merged main.

## Earlier complete snapshot: 15:30:51 UTC

The Git remote snapshot recorded at 2026-11-18 15:30:51 UTC contains 7,591
branch references: main, 7,224 ordinary branches, and 366 protected HIA
branches. The ten new references since the prior snapshot are all protected:
nine descend from the Cell/HIA root and one from the Codex HIA root.

Three pre-existing protected references advanced externally by one direct
child commit; 353 stayed unchanged. No protected reference was written or
deleted by this consolidation. The original and refreshed inventories, full
ref delta, root relationships, new commit objects, ordinary-owner chain,
and graph decisions are preserved in the original 33-member archive.

Both HIA roots and the established descendant anchor remain outside every
admitted ordinary candidate's ancestry. The learning, AuthBus, and evidence
tip d5af were checked against all 366 protected names. The d5af label in the
frozen graph file records that content review was pending at that earlier
checkpoint; the later complete content acceptance is preserved separately
under rust-evidence-d5af-a28. Fleet has its own complete latest-boundary
proof in rust-fleet-a28. These frozen proofs do not assert that other writers
have stopped updating the repository.

At this snapshot the published 770179d integration commit covers 2,064
ordinary names. The local learning plus AuthBus history join covers 2,066.
Main still covers zero ordinary branch tips, so this snapshot authorizes no
branch deletion. Publication and eventual deletion require fresh exact ref
and ancestry checks against the resulting main commit.

Each original member and every reconstructed archive byte were checked
again while preparing this checkpoint. The archive contains recorded audit
programs as evidence; they were not replayed as repository instructions.

## Reconstruct the original archive

The ordered parts are individually gzip-wrapped slices of the original
compressed archive, keeping every Git blob below 512,000 bytes. Reconstruct
from this directory with Python 3. This only writes the verified original
archive; it does not extract or execute any archived script.

```python
from pathlib import Path
import gzip
import hashlib
import json

index = json.loads(Path("archive-index.json").read_text())
chunks = []
for item in index["parts"]:
    stored = Path(item["path"]).read_bytes()
    assert len(stored) == item["bytes"]
    assert hashlib.sha256(stored).hexdigest() == item["sha256"]
    decoded = gzip.decompress(stored)
    assert len(decoded) == item["decoded_bytes"]
    assert hashlib.sha256(decoded).hexdigest() == item["decoded_sha256"]
    chunks.append(decoded)
original = b"".join(chunks)
assert len(original) == index["archive_bytes"]
assert hashlib.sha256(original).hexdigest() == index["archive_sha256"]
Path(index["archive_name"]).write_bytes(original)
```
