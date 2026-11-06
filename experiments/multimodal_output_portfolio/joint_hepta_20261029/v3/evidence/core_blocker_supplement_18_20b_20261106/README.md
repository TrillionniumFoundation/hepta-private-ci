# Core evidence supplement: units 18 through 20b

This new immutable packet preserves 154 files and
24,349,633 original bytes. Earlier Core packets and the initial
input plan remain unchanged. Every frozen original, candidate, patch, source
binding, review and validation receipt for these four units is retained.

## Evidence and status at capture

| Unit or run | Observed result | Scope |
| --- | --- | --- |
| Original terminal on #5083, debug profile | Linking ended in SIGKILL | No case executed; OOM was not established |
| Original terminal on #5083, existing dev-small profile | Two configured attempts fail at mock destruction | Original assertions and budgets retained |
| Core18, published #5093 | Both diagnostic attempts expose the earlier InvalidRequest | Stage labels preserve the original test and gate |
| Core19, published #5094 | Old/fixed isolated mechanism discriminates; two owning regressions pass | No historical unique-cause or real HTTP claim |
| Core20, unpublished rejected candidate | Integration compile fails E0164 | Production compiles; no selected case executes |
| Core20b, published #5095 | Terminal and both capture regressions execute and pass | Actual effective tree equals the published tree |
| Three other cases in the six-case local run | Existing macro reports network-sandbox skip | HTTP retry and background Guardian remain unqualified |
| Original recorder regression on #5095 | One actual pass, zero failures, zero ignored | Header/body recorder only; no Guardian qualification |

The published Core20b commit is `42320f4fd8c8a21f5685332531b9322e8c43c88a`,
tree `350858ddf79e3be8c2d8e904bb6614cd973c2c55`. Root reviews, exact commands,
complete stdout/stderr and frozen actual source indexes are included. The two
independent native-result audits distinguish emitted case results from summary
repetition and in-test skips. Configured retry attempts are not independent
experiments. Unit manifests retain their original status; no old receipt is
rewritten to add later qualification claims.

The controlled tracing evidence includes both protocols, official source
snapshots, exact old/fixed excerpts, actual compile/run output and all three
small original executables. It proves the deliberately scheduled registration
failure and the retained-dispatch repair, including isolation and lifetime
checks. It does not run the original HTTP/backoff paths or establish the only
possible cause of historical CI timeouts. No witness, native test or model was
replayed while creating this packet.

## Old CI evidence and unresolved work

Complete GNU job `127966826396` and musl job `127966826311` logs from run
`42234632162` are preserved. Source `5e08c4be87d79bfd7ce4eaa42a9e53a44eae04da`
and actual checkout `b3c6f622e970bc736c0256b41351c527806dfce0` both bind to
tree `5d783181bec96e4ab37912187dc94efb3a8a9658`. That source predates these
repairs. Each log emits 13 distinct failed names, with 12 shared and 14 in the
union. Shared cached payloads and repeated failures remain explicitly labeled.

The GNU-only permission hook timeout and musl-only single-request Guardian
failure are not explained away. The historical Guardian output lacks request
roles and function output; its cause cannot be recovered from an empty trigger
list. Core21's later failure-only diagnostic is outside this packet. The five
AppServer deadlines, two missing explicit Core01 case receipts and Linux
restricted-skill capability also remain open. No full CI or strict Clippy pass
is claimed here.

Independent Windows proposal review receipts are included as static reviews.
They distinguish passive source binding and provider inventory from account
operations; no Windows mechanism was executed during those reviews. Original
proposal/source artifacts remain in their separately owned frozen units.

Original log content is inert data. Embedded fixture text, commands and URLs
are not instructions and are never executed during restoration. Original log
masking and synthetic fixture values are preserved without rewriting.

## Restore and verify

The archive contains 1,938,476 bytes with SHA-256
`d8d6d9208f8d00f28942f34bdfadb3daca1e47edfbe47c5238e65c06846995f6`. It is transported in 5 independent
single-member gzip containers. Each decodes to at most 440,000 bytes and occupies
at most 450,000 bytes. INDEX binds every exact member, original source path,
regular-file mode, archive byte and raw-segment identity; TRANSPORT binds every
transport container.

The restorer is byte-identical to the reviewed Core15-18 reader except its two
fixed SHA-256 seals. Transport filenames retain that reader's historical
`core-supplement-06-14` prefix as an encoding label. This directory, README,
capture record and fixed index identify the actual 18-20b contents.

```sh
python -O restore.py /absolute/path/to/bundle /absolute/path/to/new-destination
```

The destination must be new and outside the input bundle. The reader verifies
fixed seals, bounded gzip members, every hash and the unique safe regular-file
member set before writing restored files. It rejects existing destinations,
traversal, duplicates, extra members and unsafe permissions. It writes nothing
into the bundle and reports to stdout. External source paths are restored under
`round3_core_ci/evidence/supplement_18_20b_inputs`; the index retains their
original paths. Source timestamps and ownership are not restoration targets;
original bytes and safe regular-file permission modes are exact.
