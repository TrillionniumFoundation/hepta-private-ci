# Rust consolidation audit, 2026-11-22

This publication repairs observed qualification failures and records three
reviewed historical merges. It also imports a separately reviewed Windows
private-artifact component. The complete Rust consolidation into `main` remains
unfinished. No branch is authorized for retirement by this snapshot alone.

## Source and history

| Stage | Commit or tree | Scope |
| --- | --- | --- |
| Previous PR source | `0ac61de676f7076bead25f86078a6c4839f1a132` | Previous qualification results only |
| Maintenance and coverage source | `c9d6cb3bdf89fa9065c25b761686fddc9a616609` | 154 changed paths, tree `5d45f6370129372cc77294088bdfe7e0b0efc28e` |
| Three historical merges | `d29f3669ece6696f086c75624dbb44cbaabee134` | Same complete source tree; actual default merges independently reconstructed |
| Windows component execution source | `7b39d8dac919c517f7defe5443de3ff4c2d52669` | Local single-parent commit on the previous source; 14 files |
| Combined source commit | `a0814f1905c580d136d97c97b371ec5af687e4f0` | One parent: `d29f3669ece6696f086c75624dbb44cbaabee134` |
| Combined source | `f842c752114f0170a55d5d01789e2da3171ff3d2` | 168 changed paths relative to the previous source |

[SOURCE-FILES.json](SOURCE-FILES.json) binds the first 154 paths.
[COMBINED-SOURCE.json](COMBINED-SOURCE.json) binds all 168 final source paths.
The Windows component is imported after the historical chain with one parent;
the original `ec6ffaa743f8ef088805a5acee7693969adefe3a` history is not attached.

The historical tips reviewed and merged are
`b40def20022b37d1cc1ca90a608795e60ebf2777`,
`e304674acbadedede0b9b1ddf0afe2bf331181e6`, and
`372e473d52e69f21e85e1ea6cfa9c3c1aff3e928`.
Each exact remote first parent was used for a default merge. Conflict stages,
permitted resolutions, all 59,439 leaf records, and preservation of all 154
source changes were verified. This is documented in
[HISTORY-REVIEW.json](HISTORY-REVIEW.json) and
[history-details.tar.gz](history-details.tar.gz).

The branch formerly pointing to `372e473...` has since advanced to
`055476ebb46451164f16cd00ae0d171f87e551cd` for
[PR #1365](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1365).
Containing the old commit does not establish containment of its current ref.

## Repairs and actual validation

The locked Prettier 3.5.3 formatted 131 workflow documents and one Markdown
file. Full YAML values, including 637 shell steps, remain identical. The
original frozen workspace install and original formatting command passed.
[WORKFLOW-REVIEW.json](WORKFLOW-REVIEW.json) and
[FORMAT-BINDINGS.json](FORMAT-BINDINGS.json) retain the comparison.

Eighteen native-maintenance outputs were reconstructed from the previous
source's real CI artifact. Seventeen files contain formatter changes; the
remaining file removes two redundant last-use clones without changing its
assertions. The original package test command passed 271 cases with two
original worker-entrypoint skips. Its original `just fix` passed without
editing source; the existing `clippy::drop_non_drop` warning remains, so this
is not a strict-Clippy success claim for that package. The original GitHub
script suite produced 314 execution records, including the original ten
duplicate test IDs. See [POSTIMAGE-REVIEW.json](POSTIMAGE-REVIEW.json),
[INDEPENDENT-REVIEW.json](INDEPENDENT-REVIEW.json), and
[local-validation-logs.tar.gz](local-validation-logs.tar.gz).

Four operator test/build files add meaningful owner-training and sensor
coverage. The original 85% requirement is unchanged. Actual line coverage
increased from 2,122/2,902 (73.12%) to 2,637/2,902 (90.87%). The default suite
passed 47/47; the compatibility suite passed 49/49, both without skips.
The original coverage command and strict Clippy in both configurations passed.
See [OPERATOR-REVIEW.json](OPERATOR-REVIEW.json). Its raw evidence is stored in
two ordered pieces under [operator/PARTS.json](operator/PARTS.json). Concatenate
the listed parts in order, verify the original byte count and SHA-256, then
open the resulting gzip tar archive. Every original member is preserved.

The separately imported Windows component adds retained private-directory and
file APIs without changing existing AuthBus, State, Operator, Shadow or sandbox
callers. The original nine backend test names and refusal assertions remain;
the junction fixture now passes a fixed command tail and verifies that the
fixture actually is the intended reparse object. The existing Windows
19-group/175-case jobs remain structurally identical. A separate job executes
the nine backend cases on the exact published source.

The component passed Windows GNU test compilation, nine Linux package tests,
five collector rejection tests, the original scoped `just fix` and formatter,
and both original Bazel lock commands. Cargo.lock and MODULE.bazel.lock remain
unchanged. These results do not establish native Windows behavior. The new
head still needs the nine native Windows cases and all original gates.
See [WINDOWS-COMPONENT-REVIEW.json](WINDOWS-COMPONENT-REVIEW.json),
[WINDOWS-INDEPENDENT-REVIEW.json](WINDOWS-INDEPENDENT-REVIEW.json),
[WINDOWS-BRANCH-DISPOSITIONS.json](WINDOWS-BRANCH-DISPOSITIONS.json), and
[windows-component-details.tar.gz](windows-component-details.tar.gz).

The final combined formatter and check passed without changing any of the
168 source hashes. No Rust tests were rerun after final formatting. This
publication keeps source-specific results separate from final-head CI.
[VALIDATION.json](VALIDATION.json) is the machine-readable summary.

## Branch protection and remaining work

The original 7,907-ref snapshot has 79,249 reachable commits, with no unknown
tips, missing parents or cycles. It protects 554 refs and 1,492 known nodes,
including 414 ref names without the letters `hia`. The previous candidate
contains 2,866 ordinary refs in that snapshot; 4,486 ordinary refs remain
outside it. These are fixed-snapshot graph counts, not a complete source-review
or current-ref deletion claim. The three new history merges contain no known
protected nodes and do not touch HIA refs.

[PROTECTION-SNAPSHOT.json](PROTECTION-SNAPSHOT.json),
[PROTECTED-REFS.json](PROTECTED-REFS.json),
[PROTECTED-NODES.json](PROTECTED-NODES.json),
[PARENT-DELTA.json](PARENT-DELTA.json), and
[refs-7907.tsv.gz](refs-7907.tsv.gz) preserve this snapshot and its identities.
The historical 551st protection pin still has no recovered identity; that
gap remains explicit. Protection is cumulative, including historical aliases.
Fresh tips and the exact final `main` ancestry must be checked before any
retirement.

The later [PREPUBLICATION-PROTECTION-DELTA.json](PREPUBLICATION-PROTECTION-DELTA.json)
records 7,908 refs at 13:52 UTC: one new ordinary name, the PR #1365 branch
movement described above, and no deletions. Every previously protected ref
retains its exact SHA. The two changed-tip closures introduce no new HIA
alias or protected node; known protection remains 554 refs / 1,492 nodes.

The 151 and 233 history clusters were reviewed but remain unmerged because
their default merges contain unresolved behavioral differences. See
[REVIEWED-NOT-MERGED-151.json](REVIEWED-NOT-MERGED-151.json) and
[REVIEWED-NOT-MERGED-233.json](REVIEWED-NOT-MERGED-233.json).
The full ec6 history also remains unmerged: 56 net paths include 16 conflicting
paths, and the 14-file component does not incorporate the other consumers.

[PREVIOUS-CI.json](PREVIOUS-CI.json) records the completed 106 checks on
`0ac61de...`: 76 success, 12 failure, 17 skipped and one cancelled. Those
results do not qualify this publication. Outstanding behavior includes the
Windows AuthBus non-Unix rejection, elevated sandbox admission, AppContainer
and LPAC mechanisms, plus all final required checks. Existing assertions,
thresholds, protection rules and the exact STOP on
`d783273c25b3164f5f632482cb7b017fdcb9d756` remain in effect. That patch and its
descendants were not read, used or replaced by an equivalent workaround.

Initial failed local attempts are retained in the archives: the incomplete
tool-only npm installation, missing sparse custody input, and the first Bazel
CA/input attempts. The subsequent runs restored the original inputs and trust
configuration without weakening the checker. Older CI failures remain actual
historical failures.

## Evidence layout

[EVIDENCE-MANIFEST.json](EVIDENCE-MANIFEST.json) records the size and SHA-256 of
every other file in this directory. It intentionally does not hash itself.
Original reports keep their original filenames inside the archives. Absolute
paths in original reports describe execution locations; their archived member
names and recorded hashes identify the corresponding portable evidence.
The independent [PUBLICATION-QA-REVIEW.json](PUBLICATION-QA-REVIEW.json) binds
the 30-file package before that review and this explanatory paragraph were
appended. Its checks cover all 168 source files, the original manifest and
archive members. The source tree remains unchanged after the append.
Large leaf inventories and parent graphs used in history reconstruction are
described by exact hashes and reproduction commands in the history archive's
`EVIDENCE-INDEX.json`; the archive contains the compact reviewed records.
