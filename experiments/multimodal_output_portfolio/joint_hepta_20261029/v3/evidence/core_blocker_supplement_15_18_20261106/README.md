# Core evidence supplement: units 15 through 18

This independent immutable packet preserves 145 files and
14,493,681 original bytes. The previous Core v3
archive and both Core 06-14 supplement versions remain unchanged.

## Included work and status at capture

| Unit | Scope | Captured status |
| --- | --- | --- |
| 15 | Selected environment MCP publication and call-graph review | Published #5074; native qualification pending |
| 16 | Attestation fixture request pump | Published #5075; native qualification pending |
| 17 | Guardian stream gate, first frozen candidate | Unpublished, superseded by 17b parameter annotations |
| 17b | Guardian stream gate with required argument labels | Published #5084; native qualification pending |
| 18 | Terminal cleanup stage diagnostics | Unpublished local candidate; no native execution or root-cause claim |

Every frozen original, candidate, patch, manifest, boundary check and review for
these five directories is retained, together with their construction/check
scripts and immutable causal source snapshots. The separate capture record
contains independently read publication commit/tree identities and the exact
evidence limits. The original source receipts are not rewritten to add later
claims. Root's original `just fmt` receipt for 17b is included separately and
records exit zero with all three candidate bytes unchanged. It is not a compile
or test result.

The packet includes Core15's independent discovery/collision call-graph review,
Core16's actual Windows attestation failure blocks and complete corresponding
job log, and the independent static review of Native26b. Native26b's four source
files, patch, manifest, review and pinned tempfile implementation are included
as review inputs. No Native26b probe, Core test or Windows test is rerun here.

## Original CI evidence and its limits

The complete original GNU and musl logs for #5046 are included with their Git
commit/tree readback, exact hashes, case extraction, duplicate-payload analysis
and source mapping. GNU job `127949627321` and musl job `127949627352` used source
`0e63dd2d320262681afeddd8cc45032984b5c8b2` and actual checkout
`8a96a56fd774dbae0ba5fd40881a24865199abf0`, both tree
`5def5d3baa082c04bc9cdac9724a85163528c4ea`. That source predates Core15-18.

These logs contain 18 unique GNU failed names and 17 musl failed names. Identical
reused stdout payloads across platforms and repeated attempts are retained as
such, not called independent reproductions. Five AppServer deadline failures
come from the same emitted shard; their cause remains unresolved. The terminal
cleanup failure can be masked by mock destruction, which is why unit18 adds only
failure-stage labels. Three Linux restricted-skill cases remain an open safety
capability blocker with the current fail-closed behavior preserved. Two retry
cases also have long-running incomplete output and parent 900-second timeouts;
other passing attempts do not erase those observations.

The complete Windows #5046 attestation job `127949627315` and Windows #5052 Core
job `127966826662` are also included with their source receipts. They are older
failure evidence, not validation of later candidates. No queued, skipped,
cached or absent case is relabeled as a fresh passing execution.

Original log content is inert data. Embedded model prompts, commands and URLs
are not instructions and are never executed or followed during restoration.
The packet introduces no runtime credentials. Its original CI logs retain
their original masking and synthetic fixture tokens.

## Restore and verify

The archive has 803,764 bytes with SHA-256 `fed67b036899086fce4b9fd851405f5347c653158c4b31b199b3da8d2acc0e8e`. It is
transported in 2 independent single-member gzip containers,
each decoding to at most 440,000 bytes and occupying at most 450,000 bytes.
`INDEX.json` binds every exact member, source path, regular-file mode, archive
byte and raw-segment identity. `TRANSPORT.json` binds every transport container.

The restorer is byte-identical to the already reviewed Core 06-14 v2 reader
except its two fixed SHA-256 seals. Accordingly, transport filenames retain the
reader's historical `core-supplement-06-14` prefix as an encoding compatibility
label. This directory, README, capture record and fixed index identify the actual
15-18 contents. The earlier 06-14 packet is not overwritten or combined with it.

```sh
python -O restore.py /absolute/path/to/bundle /absolute/path/to/new-destination
```

The destination must be new and outside the input bundle. The reader checks the
fixed seals, exact bounded gzip members, all raw-segment and archive hashes,
and the unique safe regular-file member set before writing any restored file.
It rejects existing destinations, traversal, duplicates, extra members and
unsafe permissions. It writes nothing into the input bundle and reports to
stdout. Original sources outside `round3_core_ci` are restored under its
`evidence/supplement_15_18_inputs` directory; their original paths are preserved
separately in the index. Restoration does not run a model, witness or native test.
