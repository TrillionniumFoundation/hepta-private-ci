# Owner recovery and FinalUse FIFO: local component evidence

This directory preserves the retained small evidence files from the 2026-10-30
owner-recovery work. It is **local component regression evidence**, with no
production, PN1–PN6, whole-chain post-quantum, or cross-environment binary
reproduction qualification. Final publication is recorded separately.

## Contents and integrity

- `manifest.json` is the external inventory and records archive integrity,
  stage boundaries, source-object mappings, limitations and every member hash.
- `pn-owner-recovery-20261030.tar.gz` contains original retained logs, patches and source manifests,
  the small FIFO evidence directory, clearly labeled earlier drafts, and a
  derived Git tree/blob inventory. `INDEX.json` inside the archive records its
  payload inventory without a self-referential archive checksum.
- Original evidence bytes are preserved, including failed builds, failed
  intermediate suites, warnings and zero-byte successful formatter logs.
  Empty formatter logs alone are not exit-code attestations; completion records
  remain in the corresponding source/evidence manifests and execution record.
- Native executable bytes are excluded. The small current-binary inventory is
  included as metadata only. Its hashes were read after GREEN, and it makes no
  claim that historical RED executables were preserved.

Archive SHA-256: `bce002660d5684eec8fa3fcfab1262c66b3dfcd13f0ff56f27a1b70af7d7ad36`
Archive size: **197,494 bytes**. Retained payload: **78 files**,
**1,227,359 bytes**, plus the internal index.

## Results and accounting

| Evidence stage | Retained result | Interpretation |
|---|---|---|
| Initial `6850ae0` owner fix | RED 0/1; GREEN 103/103 | Superseded historical implementation. |
| Initial typed-ACK proposal | RED 0/1; selected GREEN 1/1; intermediate fixture failure 104/105; final 105/105 | Superseded. Its competing migration 21 must not be reapplied. |
| Adopted `f874d948`, Stage A | RED 0/1; first 129 GREEN with one flaky result; clean final 129/129 | Atomic original-owner validation precedes durable observation append. |
| FinalUse FIFO | Initial ENOSPC before tests; actual RED 5 pass/1 fail; GREEN 6/6 | The protected reader rejects a FIFO without waiting for a writer. Sandbox-fix and uv-cache formatter failures are retained. |
| Stage B, schema 22 | Initial E0308 before tests; actual RED 2 pass/2 fail; GREEN 133/133 | Legacy unresolved attempts and already-open old writers fail closed; migration 21 bytes remain unchanged. |
| Column metadata follow-up | First and definitive default-change RED retained; GREEN 134/134 | Checks the four append columns' exact SQLite type/null/default/key/hidden metadata. |
| Stage C, Agentd expiry | RED 1 pass/1 fail; GREEN 6/6; final scoped Clippy passes | Original operation can be observed after lease expiry; a new dispatch still needs a live lease. |

**The final AutomationStore count is 134, not 129 + 133 + 134.** Those are
overlapping package suites at successive source states. The initial 103/105
results are also historical, not additions to the final total. Agentd HTTP6 and
the separate FIFO6 are different selected component runs; this bundle does not
convert them into a whole-system pass count.

The Agentd HTTP6 filter includes four existing controls and two expiry controls.
The positive case performs POST Accepted, closes and reopens **AutomationStore's
SQLite handle**, then performs GET Completed after the original lease expires.
The exact request sequence is POST then GET, including the repeated terminal
reconcile. This is **not a whole-Agentd process restart**. The negative control
has a valid grant and an expired lease and observes zero HTTP calls and zero
provider attempts. The run excluded 220 unrelated Agentd tests.

The FIFO local run executed six V2 component cases. The separate CLI-bound
`native_app_server` control in its seven-case CI roster was not executed by that
local selector. ENOSPC and E0308
occurred before test execution and are build-blocker evidence, not vulnerability
RED. The first f874 run's flaky result remains visible alongside its clean
replacement run.

The actual FIFO RED/GREEN ran on Stage A's `00012a4` base. Each of two failed
nextest attempts bounded a blocked child at five seconds, then killed and reaped
that child. The fix affects the shared V1/V2 protected configuration reader; it
does not enable ordinary worker V2 or provide its protected time source and
durable external frontier. Corrected scoped `just fix` succeeded without adding
`-D warnings`; the successful formatter reused `/tmp/hepta-pn-uv-cache`.

## Source boundaries and prepared objects

The adopted base is `f874d948a38c119e57b1368adab79437956acd78`, tree
`54c15dd602094d62005b02256046d9f3ca9178a4`. The table identifies local stages and
the prepared GitHub objects supplied by the root coordinator. The root reported
each prepared tree equal to its local stage; this bundle independently reads the
local tree and changed source blobs. **A prepared commit object is not a branch
publication receipt.** The final published SHA will be recorded in a separate
receipt; it is not inferred from this table.

| Stage | Local commit | Source tree | Prepared GitHub commit |
|---|---|---|---|
| stage-a-f874 | `00012a4b64cade759833b24eedc6390d170777e2` | `f2bf3e9f8af17619fd56f94e35f7429475dd0fe4` | `63ef06334387a07d8c47777c73c2e8582b7fe846` |
| fifo-config | `434e7486c640bb01b9a6e0124209e913a377a136` | `4a0ae56092ca4cecd3686f01212d16fed28affe9` | `089312b1d1d95cb72e601ffd53aa643834b13829` |
| stage-b-schema22 | `0fa93fd32557a340901e15836bdf471b369dd5d1` | `10ca0f98540906224c1a97265d88198576f32215` | `d6818075db79f6a95f667670e22d9e290d09236f` |
| stage-b-column-metadata | `ef886ca57b79e031031238cee892bcc0c434dbc6` | `ec209535097c2f38ab04160a8a5283a39cf6f77f` | `6b62e8dde5de2a34e1e9714147089fc155b5fd04` |
| stage-c-agentd-expiry | `098c1a85b40dcc27d1d51c5dbefa6c0ebe474402` | `320f9b28b459fe475ca91359fc7ee91821a76503` | `ea929be38b582360d1fa985d16577684f804e435` |

`derived/git-source-objects.json` includes the changed paths, Git blob IDs,
SHA-256 values and sizes. These immutable source identities are primary; a commit
SHA alone does not prove that a later formatted tree was the exact native test
input. The original tested-source and final-source manifests are both retained.

The initial `6850ae0` work is preserved by local stage `28e3558df785e4fef93d446692b6229f6ef1de26` and the frozen
WIP object `870d3045025178fec240d1e587f24430b2402bf8`. The WIP also contains parallel work, so the derived initial
provider-ACK object inventory is limited to that original patch's paths. Its
later frozen state does not manufacture an exact earlier test-source snapshot.
The source index records its separate untracked tree and the retained branch/tag.

After Stage C's native six-test GREEN, one test helper's `expect` was converted
to a fallible `Result`, then formatted. Its production source stayed byte-identical.
Final scoped Clippy compiled the final files successfully. No native test repeat
solely after formatting, or cross-environment binary reproduction, is claimed.

## Receipt and migration limits

`ProviderEffectAck` has **no provider signature**. Keeping complete typed ACK
content, canonical bytes and source-sensitive digests preserves what the adapter
observed. It does not create provider authentication; authenticated endpoints and
the adapter trust boundary remain separate concerns.

Older unresolved attempts with no complete binding remain **recovery-only / Unknown**.
A later Completed(B), opaque terminal observation or ProvenAbsent cannot be used
to invent the identity of a lost original Accepted(A). Existing fully typed v21
bindings may continue the same operation, but **v21 cannot prove that no historical
ACK was lost**. Schema version, key format and timestamps cannot reconstruct
vanished history. Existing terminal history stays readable without retrofitted
bindings. The schema22 old-writer controls include connections prepared before
upgrade; they do not confer authority on arbitrary database mutation.

## Deterministic packaging and verification

Only small retained files were read; no native test, compile or binary was run
to make this bundle. The archive uses sorted member names, USTAR regular files,
mode `0644`, numeric owner/group zero, empty owner/group names, mtime zero, and
gzip level 9 with empty filename and mtime zero. Two independently built byte
streams matched, and every extracted member matched its source bytes. This is
packaging determinism, not native build reproducibility.

Run this read-only check from this directory to verify the archive and members:

```python
import hashlib
import json
from pathlib import Path
import tarfile

manifest = json.loads(Path("manifest.json").read_text())
archive_path = Path(manifest["archive"]["path"])
assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == manifest["archive"]["sha256"]
with tarfile.open(archive_path, "r:gz") as archive:
    for item in manifest["files"]:
        member = archive.getmember(item["archive_path"])
        assert member.isfile()
        content = archive.extractfile(member).read()
        assert len(content) == item["bytes"]
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
print("archive and retained members verified")
```
