# E6 retained native evidence — 2026-11-21

This is an evidence-only package. It neither changes nor re-executes the
implementation. The current executed source is
`84721f3da92ffaac3e7c7e2e39de2df985834370`, tree
`ec318c4d77695a67f11a2a9ec174e3c8f19823df`. The later commit containing this
package is an evidence commit, not the executed source. Historical files keep
their own original source identities and stage-specific statements.

## Results preserved, with their scopes

| Retained lane | Actual result and limit |
| --- | --- |
| v1 setup | Failed while reading an unavailable promisor Git object; no compiler/lint work claimed |
| v2 source gate | Original 54 modules / 474 tests: 17 errors; original stderr and terminal result retained |
| First locator repair | 13 selected protection rows passed and one failed; retained without replacement |
| Final locator review | Selected 14 and the original two QA modules passed; historical repair bytes retained |
| v3 source and diagnostic continuation | 474 source QA tests, full CALLERS gate and four diagnostic controls passed; full inventories and original outputs retained |
| New source's original components | Seven canonical JUnit files: 11 + 16 + 5 + 2 + 2 + 11 + 18 = 65 cases, zero failures/errors/skips |
| Complete NoUpdate16 owner | Four canonical JUnit files, one case each, all passed; `complete_native_NoUpdate=true` |
| Official daemon CI | Run `44862741031`, job `136719540259`: 2,183 passed / one failed of 2,184; Root suite was not executed |

The official CI failure is
`cell_generation_control::tests::lost_rpc_reply_and_queue_capacity_cannot_duplicate_original_dispatch`,
whose terminal helper observed `CommitUncertain`. The entire returned
4,382,919-byte job log and the source-specific analysis remain included. The
analysis records a plausible timing/uncertainty mismatch, not an established
root cause or proof that the failed run dispatched exactly once.

NoUpdate16's four canonical XML paths, relative to
`e6_patch/host_readback/originals/noupdate16/`, are:

- `complete-noupdate-16/root-completed-refusal-original-bounds.xml`
- `complete-noupdate-16/root-completed-refusal-observer-namespace.xml`
- `complete-noupdate-16/root-ack-lane-mechanism.xml`
- `complete-noupdate-16/ordinary-post-a-no-update.xml`

Prior JUnit files and `fresh-native-observed` copies remain in the evidence but
do not add cases. The original NoUpdate15 failure is retained. NoUpdate16 did
not reproduce that failure and emitted no `root_diagnostic` line, so this
package does not claim that the diagnostic patch fixed the old root cause.
No Adopt, cold run, fresh D after cold recovery, production FinalUse, settlement,
learned-child improvement or generalization is established. The original
qualification limits and `qualified=false` fields remain unchanged.

| NoUpdate16 timing scope | Seconds |
| --- | ---: |
| Ordinary JUnit testcase | 96.023 |
| Original ordinary executor | 96.91921981424093 |
| Ordinary wrapper stage | 96.97251540236175 |
| Complete owner, including preparation | 308.8090741466731 |

These intervals overlap; do not add them. The separate 65-component owner took
55.884070318192244 seconds. Compiler and lint cumulative work, their separate
1,800-second ceilings, setup stages and incomplete full-system cost accounting
are preserved in the original reports. Passing a bounded lane does not imply
that the official full suite passed or that total physical cost is known.

## Byte preservation and new container

`MEMBERS.jsonl` maps every selected original/review path to its byte length and
SHA-256. Identical byte strings share one `objects/<sha256>` member in a new
deterministic tar/gzip container. Empty files, repeated inventories, historical
failures and duplicate JUnit copies keep distinct logical paths. No original
file is parsed and rewritten as a substitute for its bytes.

`ORIGINAL_CONTAINERS.jsonl` retains the original outer-container identities and
the member mappings verified against them before repacking. Core originals:

| Original outer container | Bytes | SHA-256 |
| --- | ---: | --- |
| `20_v3_terminal.tar.gz` | 6,825,136 | `643c13640912745e622c49df228a182fa4b7438a6c1b39b83d8d3ac559cb6230` |
| `22_native65.tar.gz` | 130,725 | `059f6214fb450a94f7907aadaf9489db8ea7ce6ff909da3433efd886a3891987` |
| `27_noupdate16.tar.gz` | 2,062,311 | `c17961d96a985a26213c633d6ebd140944dc1019f53c21eb2acb4ea615f59451` |

Their 46, 95 and 91 regular tar members respectively include readback manifests;
counts of underlying captured files must not silently include those manifests
as additional test executions. Local readback summaries are separately retained.
The original native-review bundle and CI gzip-copy identities are also indexed.

**The new container is not a copy of any original outer gzip bitstream.** Every
indexed file's original bytes can be restored, but original tar header ordering,
filesystem metadata and gzip compression bytes are not reproduced. Original
outer-container hashes cannot be recomputed merely by recompressing the new
pack. Those original tar/gzip files remain in the retained workspace; their raw
members and observed identities are what this package publishes.

Original text readback observations through phase 27 remain intact. Repeated
binary transport fragments and outer compressed wrappers are not independently
republished when their complete decoded originals/full CI log are retained.
`packaging/OMITTED_TRANSPORT.jsonl`, restored from the pack, identifies the exact
transport representations omitted, with original sizes, hashes and reasons.
Python bytecode caches are outside the selected evidence scope. All historical
execution/review inputs, raw original readback trees, locator outcomes, canonical
JUnit and complete official CI log selected by `MEMBERS.jsonl` are retained.
Historical notes are kept as written; the later terminal summaries supplement
them instead of rewriting earlier failures or earlier authorization statements.

## Existing blob policy

Later lifecycle planning/readback is outside this NoUpdate16 terminal snapshot.

The executed source's [workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/84721f3da92ffaac3e7c7e2e39de2df985834370/.github/workflows/blob-size-policy.yml)
uses the [original checker](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/84721f3da92ffaac3e7c7e2e39de2df985834370/scripts/check_blob_size.py)
with `--max-bytes 512000`. Copies of both exact policy files are in the evidence.
Each new gzip segment is stored as a real binary Git blob of at most 360,000
bytes. Git API Base64 transport does not become a text file in the repository.
Every published file stays under 512,000 bytes. No allowlist, ignore rule, ceiling or execution-source file
is changed. Historical allowlist preimages inside the evidence are data only.

`CHUNKS.jsonl` binds binary chunk order, offsets, byte lengths and hashes.
`MANIFEST.json` binds the member/chunk/container indexes, full new tar/gzip
digests and the verifier. All package files are required; an incomplete commit
stage cannot be verified or treated as a complete archive.

## Verify or restore

From this directory, run the standalone standard-library verifier:

```sh
python3 -B verify_restore.py
python3 -B verify_restore.py --restore /absolute/new-e6-evidence-directory
```

The first command verifies every chunk, the new complete container, every unique
object, every logical member and each original container's member inventory.
The second additionally writes the indexed files into a new directory and
refuses to overwrite an existing destination. It does not execute or import any
archived script, call a model, run native tests, or contact a host. Hash checks
establish byte consistency with this manifest; they do not independently
authenticate original actors or confer scientific, adoption or reward status.
