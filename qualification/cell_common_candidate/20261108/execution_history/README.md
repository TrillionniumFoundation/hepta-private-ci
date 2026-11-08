# Source-bound execution history

This is a bounded, lossless checkpoint of engineering evidence. It preserves
selected original archives, including failures and preparation errors. It does
not certify complete history, complete cost, production authority, ordinary
daemon closure, or any S0–S5 advancement.

## Source identities and observed results

| Source                                                                                         | Original observed result                                                                                                                                                                                                                                  | Boundary                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `6fd7471bce6102de857c0c7f9da5d5e641b719f7`                                                     | 126 independent Python fixtures passed; full caller scan failed. The native run retained an ACT1 timeout.                                                                                                                                                 | Original failures remain in the history.                                                                                                                                                                                 |
| `86ac7796345ec0a885bb212e5174ba85bb16485e`                                                     | 127 Python fixtures and full caller scan passed.                                                                                                                                                                                                          | The full scan exceeded the original CI budget. UI preparation used a separately recorded dirty patch.                                                                                                                    |
| `09f543c732e383a62f9339e84b69b373992d6e07`                                                     | 130 Python fixtures and full caller scan passed. The scan took 371.628 seconds under the original 600-second cap. The local native chain executed 700 core-family cases, 729 agentd cases, and one original HostCAS case successfully.                    | These are scoped local executions, kept separate from overlapping CI and preparation runs.                                                                                                                               |
| Original native CI run `42523028203`, source `09f543c`                                         | The complete default workspace executed 20,562 unique passing cases, with 139 skipped in the original raw summary. All three jobs completed successfully. Four original artifacts and their receipt/log/JUnit/source bindings were independently checked. | The 7,910-case scoped and 1,214-case mechanisms sets are subsets and are not added again. Original HostCAS and Python 23+6 are separate. This does not qualify a later source or the independent Windows/macOS failures. |
| UI source `09f543c` and explicit base merge `e422c96f016da757a87134f33923633721702796`         | Each lane passed seven SDK cases and fifteen real browser cases across Chromium, Firefox and WebKit, plus both pixel reports. Original retries, skips and unexpected results were zero.                                                                   | The two tested commit identities remain distinct; their trees matched. Counts across lanes are not added as distinct coverage.                                                                                           |
| Generic PR merge `f7fca4fe3be11c4bc266597e3c2e5205f10f49e7`                                    | Original Windows and macOS failures are retained with complete raw logs and job metadata.                                                                                                                                                                 | Its tree matched v3, but the tested merge commit is not relabeled as source-head execution.                                                                                                                              |
| `ce754c38d6418765ba39eefaf80a1a1e174dfd9d`                                                     | 130 independent Python fixtures, original self-test, exact CURRENT comparison and full caller scan passed. The scan took 380.989 seconds under the original 600-second cap.                                                                               | Source stayed clean and unchanged. This Python result does not qualify its failed native compilation or the later observer correction.                                                                                   |
| `5fd02472b62b411ead6ad8d59f1d91a604433516`                                                     | The corrected owner observation/recovery scope executed all 23 selected cases and five owning-package strict checks successfully, without source edits.                                                                                                   | The earlier ce754c3 three-error compile failure remains in a separate original packet. This is not relabeled as final-source execution.                                                                                  |
| `ba4e1e42b6a8cbab724e1755bddfb9b5b8f298a1`                                                     | 130 independent Python fixtures passed; full caller scan 375.202 seconds; original native chain 701/729/HostCAS1 passed with actual discovery-to-fresh-JUnit comparison. The separate core/memory 4 and queue 4 scopes also passed.                       | Original source, budgets, watchdogs and zero-retry behavior remain bound to each receipt. Scopes and repetitions are not summed into a full-workspace result.                                                            |
| Windows original 33, tested source `ba4e`, observer `2fccd13676ee45061f49a3d397631900440c4d38` | 33 actual cases passed with zero failure, skip or retry. Windows owning-package strict lint passed, and both checkouts remained clean.                                                                                                                    | The observer's source is distinct from the source being tested. The original CI did not upload its native test executable; that limitation is retained.                                                                  |
| `ba4e`, repository quality and dependency graph                                                | Original Codespell, format and blob gates passed. A missing-UV PATH failure preceded the same-source format recovery. Two local Bazel dependency-resolution attempts timed out at the same 300-second bound.                                              | The Bazel gate is not passed; its root cause is not established. New complete CI is a separately observed, initially nonterminal execution.                                                                              |

The v3 tree is `9be76894a2984d28e1780a7ff7499c79f506b09a`.
The ce754c3 tree is `c329c638bd48187927f34e4fdda5a5274321d48d`.
Its later, separately committed test observer correction is
`5fd02472b62b411ead6ad8d59f1d91a604433516`, tree
`05252023acf4e40cd23d26c3c571cdb029b4c2f0`. Preparation and execution
identities must not be interchanged.

The published final common tree is
`d2f261084bad25c230b95835e9a589fe7b866be1` at the ba4e commit above.
Its Cargo/Bazel/pnpm lock bytes and formal CURRENT bytes stayed unchanged by
the latest repair series. Original 09f native CI used 86ac as its receipt base;
this is preserved independently of the integration's common 1eb starting point.

The 700-case local scope is exactly `codex-hepta-contracts`,
`codex-hepta-neuron`, `codex-hepta-automation`, and
`codex-hepta-bellman-operator`; it is not the `codex-core` suite. Original
ignored and filtered cases remain separately recorded.

The final 701-case scope has the same four package owners. The final native
commands separately reported 14, 63, 791, 2,863 and 34 skipped or filtered
cases for core-family, agentd, HostCAS, core/memory and queue, respectively.
Selected cases passed without retries or selected skips; the other cases
are not counted as passing.

A non-atomic API snapshot at 2026-11-08 23:28:37–23:28:48 UTC captured 18 new
workflows associated with ba4e: eight successful, seven in progress and three
skipped, with no completed failures. The native, full repository, UI and
original Windows workflows were still nonterminal. The advertised PR merge
`f9d3da90698b470ffc9f8acecd73ca0a54dbfe4d` is not treated as a verified tested
checkout. The snapshot's successful Bazel proposal job produced proposal
metadata; it does not replace the two timed-out local lock-gate receipts.

All source-bound Python packets retain the unchanged research result hash
`c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4`.
**S0, S1, S2, S3, S4 and S5 remain HOLD.**

## Platform preparation and actual release consumption

The Guardian/pagination preparation packet preserves the first compile and
metadata failures, four actual native passing cases and owning-package lint on
preparation commit `57556e4ed0b5cbba2fd20f106591ad3dce8eff9b`. It is not a
final common-source Windows execution.

The macOS Notes diagnostic uses the exact four original I/O function bodies.
It preserves the immediate-peer-close failure and 1,024 held-peer successes.
It is a narrow native diagnostic, not whole-crate qualification.

The zsh C preparation packets retain original Linux and macOS failures and
actual patched builds. The first tag, `codex-zsh-v0.1.1`, remains intact: its
two Linux jobs passed, while both macOS jobs failed runner admission before
execution and publication was skipped. No original run was rewritten or
cancelled to obtain a successful receipt.

The subsequent `codex-zsh-v0.1.2` tag targets
`7a0f14490ad36cd6d23d2d06b522735d66710d48`. Its four native platform builds,
smoke checks, metadata job and publication completed successfully. The
existing Python package resolver anonymously downloaded and checked all four
real asset sizes and SHA256 values. The existing DotSlash 0.5.9 entry point
executed the published Linux x64 and macOS ARM64 packages in fresh caches.
Initial orchestrator rejections remain in the packet.

Both final consumer manifests are pinned to the real 2,702-byte release
manifest with SHA256
`f9374bd9434680fa5ec64cc8387ee1ba74b7d843a1fbbd25131b17687b65250d`.
The Linux asset names include `musl`, but the actual binaries are dynamic
glibc ELF files; their names are not evidence of musl compatibility. Native
package execution is not substituted for the original Rust zsh tests.

The original pinned Linux archives were downloaded and checked against their
old manifests. Old and new binaries have the same observed loaders, NEEDED
library sets and complete GLIBC symbol-version sets through 2.38. This does
not establish complete ABI equivalence or general Linux compatibility.

The Windows diagnostic history retains the first original 31/33 result and 16
fixture contrasts, followed by a Python-only 22-by-two environment study.
Adding only ProgramData, including the path returned by the OS known-folder
API, admitted the exact namespace and rejected the wrong namespace. Removing
it while adding all 14 other allowlisted variables retained the original 255
failure. An empty value also initialized the observed binary; this observation
is retained, but production uses the validated nonempty absolute OS path.
The original Windows 33 were then executed successfully on the final common
source. Diagnostic observations never replace that native gate.

## Verification and reconstruction

Run from any directory:

```sh
python3 qualification/cell_common_candidate/20261108/execution_history/verify_packets.py
```

To reconstruct exact original archives into new files, add
`--reconstruct-dir /absolute/path/to/output`. Existing output files are never
overwritten. The verifier does not extract or execute archive members.

Each compressed archive is split into ordered chunks of at most 490,000 bytes.
Packet manifests bind the order, offsets, sizes and hashes, exact original
archive hash, and every original file member. Reconstruction and member
verification are completed before publication. Original inventory and bounded
publication pattern reviews are retained separately; a pattern scan is not a
complete secret-detection claim.

## Scope and costs

Packets overlap earlier history. Member counts, test counts and wall times
must not be added across repetitions, nested wrappers or source versions. A
passed command is not necessarily a test execution. Tests outside a selected
scope remain skipped, filtered or not run as recorded by the original runner.

The first checkpoint's classification retained four log references with only
path linkage and 60 unknown log paths as host-only observations. That
historical classification is preserved. It does not certify a complete
present-day inventory. Large native executable sets and tool caches are
represented by retained paths and content hashes where recorded; they are not
all packaged here.

Physical, CPU, learning and complete history costs remain unknown. Original
wall intervals remain wall intervals. No aggregate cost is inferred from
them. Evidence publication uses a separate Git branch and does not change any
source commit tested by an original receipt. Publication commits are recorded
in external Git readback receipts, avoiding self-referential manifest hashes.

The ordinary daemon still needs a concrete learning-owner implementation and
bootstrap, original registered checkpoint capability delivery, independently
authorized stage-result producers, supported effective CellBundle loading,
and actual successor-task consumption. Strong baselines, independent tasks,
multi-generation adoption and complete costs are separate acceptance work.
