# HIA components: revision-bound joint qualification

## Current source follow-up: inline UTF-8 boundaries and word equality

Source commit `82b35fed31d860f647d7ac01226877ab13ec4515` changes only the inline HIA kernel,
its ABI contract and literal raw harness. Fold and Resolve validate the
stored suffix cut and any stored opener start/end as UTF-8 scalar boundaries
after the existing geometric checks. Equality compares complete guarded
eight-byte words and the unchanged byte tail; ordering and caller effects
are unchanged. The 96-byte frame, lock, compiler pin and Rust source remain
unchanged. This does not assert speedup.

All 43 original literal cases remain; 20 additional cases are configured
(63 cases, 504 planned calls over the existing capacity/fill matrix).
No fresh build, native execution or runtime qualification has been completed
for this source follow-up. The 37 configured modules, 34 opt-in caller
kernels and three retained oracle-only kernels are unchanged. Production
dispatch, whole product, platform, performance and retirement remain open.

## Prior source increment: generic inline hidden tags

The following local component results and source descriptions belong to
the previous exact revision `450f22e370ce8db88a53ca6bbbae55262cbdab6e`, not to the new follow-up.
The original metadata and all evidence remain accessible at that revision.

`InlineHiddenTagParser<T>` now selects the `inline_hidden_tag` HIA owner under
`hia-native`. HIA owns literal search, earliest-position selection, longest
opener and first-spec tie breaks, proper-prefix suffix retention, open/close/
stop commands and EOF routing. Arbitrary nonempty Unicode delimiters and the
original non-nested grammar remain supported.

The [buffer contract](inline_hidden_tag_buffer_contract.json) binds a 96-byte
request/reply. Each native fold borrows the complete pending and delimiter
strings. There is no one-MiB string limit, aggregate framing or spec-count cap.
HIA validates capacity and state before writing; both borrowed strings and
the output tail remain unchanged.

Rust retains the original fields, spec `Vec`, pending `String`, active body,
per-call output, standard `Debug` and exact generic `Clone`/`Eq` and drain
order. The adapter validates the full response before mechanical effects.
All five original generic tests and their assertions remain unchanged.

The current source configures **37 modules and 34 opt-in caller kernels**:
35 borrowed-buffer and two scalar profiles across eight build owners
(9 + 7 + 3 + 8 + 1 + 1 + 4 + 1). The installed CLI still requires 31 symbols.
`inline_hidden_tag`, `utf8_stream` and `uuid_find` are library-only owners;
three retained oracle-only modules remain.

Local Linux x86-64 GNU execution used the unchanged compiler revision
`0de5657a80f96b138525ac7ee9ce11712a83a10d` and Rust 1.96.1:

| Gate | Observed result |
| --- | --- |
| Fresh native-selfhost full-native37 build | All 37 modules and link bindings built |
| B1 / B2 / B3 | Identical `76fe758b...9273` images |
| Generic inline literal raw ABI | 43 cases, 344 native calls passed |
| Seven retained raw ABI suites | UTF-8, output lines, item budget, environment display, citation, proposed plan and fuzzy match passed |
| Public stream-parser owner, native feature | 85 passed, zero skipped |
| Public stream-parser owner, default feature | 65 passed, zero skipped |
| Strict Clippy, both selections | Passed with all targets and warnings denied |
| `just fix`, both selections, and `just fmt` | Passed; Rust source hashes unchanged |

New public cases exercise scalar split points, overlapping delimiters, exact
per-call results and Debug state, EOF reuse, strings and delimiters above one
MiB, 4097 specs, custom Clone/Eq effects and a recoverable Clone panic. Native
decoder tests reject malformed response fields before effects. Raw cases use
literal expected states and commands, two fill values, short/exact/extra
capacities and whole-buffer guards. Source, build, report and corrected early
fixture/lint failures remain bound in [verification.json](verification.json).

Current raw gates select full-native37. Earlier profiles and defaults keep
their exact module sets. Full current/historical CI, other owner/Core/UI and
installed gates, supported platforms, search performance, default release and
retirement remain pending. Local component success does not qualify them.

## Earlier source increment: streaming UTF-8 validation

The following preserves the 36-module local qualification record. Its counts
and pending statements belong to that source; the current increment is above.

`Utf8StreamParser<P>` now selects the `utf8_stream` HIA validator under
`hia-native`. HIA decides complete, invalid or incomplete UTF-8 and the exact
original `valid_up_to` / `error_len` values. It reads the complete borrowed
byte slice and returns four little-endian u64 words in a 32-byte output.
The [buffer contract](utf8_stream_buffer_contract.json) binds the source and
capacity precedence. The input has no new one-MiB or framing limit.

Rust keeps the original pending `Vec<u8>`, five validation call sites, whole
chunk rollback, inner-call boundaries, EOF handling and `into_inner` behavior.
The native adapter checks the complete return and result shape before it
constructs a borrowed string. It has no Rust UTF-8 validator fallback.
The six original UTF-8 tests and their assertions remain unchanged.

The current source configures **36 modules and 33 opt-in caller kernels**:
34 borrowed-buffer and two scalar profiles across eight build owners
(9 + 7 + 3 + 8 + 1 + 1 + 3 + 1). The installed CLI gate still requires 31
symbols. `utf8_stream` and `uuid_find` are public library-only owners; no new
CLI reachability is claimed. Three retained oracle-only modules remain.

Local execution on Linux x86-64 GNU used the unchanged compiler revision
`0de5657a80f96b138525ac7ee9ce11712a83a10d` and Rust 1.96.1:

| Gate | Observed result |
| --- | --- |
| Fresh native-selfhost full-native36 build | All 36 modules and link bindings built |
| B1 / B2 / B3 | Identical `76fe758b...9273` images |
| UTF-8 literal raw ABI | 25 cases, 200 native calls passed |
| Six retained raw ABI suites | Output lines, item budget, environment display, citation, proposed plan and fuzzy match passed |
| Public stream-parser owner, native feature | 72 passed, zero skipped |
| Public stream-parser owner, default feature | 54 passed, zero skipped |
| Strict Clippy, both selections | Passed with all targets and warnings denied |
| `just fix`, both selections, and `just fmt` | Passed; Rust source hashes unchanged |

The new public cases exercise rollback after a completed buffered scalar,
partial EOF recovery, empty pushes, exact inner-call boundaries, scalar split
points and input above one MiB. Native differential cases compare 111,996 raw
byte inputs against `std::str::from_utf8`, including every one- and two-byte
input and the three-/four-byte scalar boundary classes. Raw ABI cases compare
whole output buffers and source/workspace guards with both nonzero and zero
fills. The exact source, build and report bindings are recorded in
[verification.json](verification.json#local_component_evidence).

Current raw gates select full-native36. Earlier profiles retain their exact
module sets and defaults. Historical CI and prior source records keep their
own scope. Complete current/historical CI, the other public/Core/UI/installed
gates, supported platforms, performance, default release and retirement remain
pending. Generic inline-tag grammar and state are the next stream-parser owner.

## Earlier source increment: Unicode fuzzy matching

The following preserves the 35-module source-preparation record. Its pending
claims describe that earlier increment; current local execution is recorded
above and does not establish complete fuzzy owner/UI or product qualification.

The complete `fuzzy_match` source unit moves the original public matcher into
HIA under the opt-in feature. HIA owns the pinned Rust 1.96.1 / Unicode 17
lowercase tables, haystack scalar lowering, whole-needle Final_Sigma context,
Case_Ignorable precedence, NUL retention, greedy matching, original-scalar
index deduplication, prefix preference and score arithmetic.

The current source configures **35 modules and 32 opt-in caller kernels**:
33 borrowed-buffer and two unchanged scalar profiles. Eight Cargo build owners
account for the links (9 + 7 + 3 + 8 + 1 + 1 + 2 + 1). The fuzzy-match crate
adds its link through TUI's feature forwarding and the existing CLI route.
Installed CLI admission requires 31 symbols, with one library-only symbol
and three retained oracle-only modules kept distinct.

Kernel source origin: `ea64655b0152ff2a5009b01a8f45df28e6147702`.
The [buffer contract](fuzzy_match_buffer_contract.json) binds its complete
202030-byte source, blob `27c9136b4dd3229a9c4536164b06af61acf90e3e`. Its
unassigned contract commit field stays null; this actual origin is recorded
in the current roles and migration metadata instead of inventing a commit.

Begin, LowerHaystack, LowerNeedle and Match use 32 finite u64 state words,
a 320-byte request prefix and a 384-byte response prefix. UTF-8 frames carry
at most 4096 bytes ending on complete scalars; Match carries at most 128 hay
records and 128 needle scalars. The whole u64 wrapper result is validated
before Core status. Structural INVALID, actual counter overflow and SHORT
checks precede every store, and the workspace stays untouched. The compiler's
known one-MiB seed-wrapper limit does not define a production string cap.

Rust retains mechanical framing, owned containers, complete response/state
and command validation, direct fixed-anchor checks and result storage. HIA
chooses the score and its first overflowing original i32 primitive; Rust
replays only that ordinary primitive to preserve the actual compilation
overflow-check policy, without guessing it from debug assertions. There is
no Rust lowercase, search or score fallback. Strings and normalized vectors
have no new aggregate semantic limit. Allocation, OOM and panic timing are
not asserted equivalent to the original implementation.

The raw gate contains **242 planned calls**: 16 literal streams with 70 calls
and 172 standalone frames. A small manifest binds four exact-name, size and
SHA-256 JSON shards, whose largest file is 308312 bytes. Every file remains
below the unchanged 512000-byte source limit; the earlier oversized draft is
not part of this source unit. Huge u64 history fixtures are logical states,
not evidence that giant real workloads ran. No reference matcher computed
the expected results.

All eight original matcher tests remain. One new public method checks 50
hand-derived literal rows under default and native selections. Thirteen
private native decoder methods check invalid frames and transitions. Two
native-only public tests carry inputs above one MiB; large default execution
is not claimed. Five focused original UI regression groups run under both
selections. The two skill-popup ranking oracles use the real matcher;
selection-popup rendering uses supplied indices, command-popup logic is
independent exact/prefix matching, file-search-popup checks paging, and the
skills-toggle view routes through `match_skill`. These groups are not five
direct matcher callers and do not establish whole-default-TUI coverage.

Current raw gates explicitly select full-native35. Earlier exact29 through
exact34 profiles retain their closed module sets and defaults. Fresh B1/B2/B3,
all 35 module bindings and every static-link receipt are required. The
historical exact74d1 job and both 60-minute job budgets remain unchanged.
Previous34 source state is retained in `previous_source_increment_34`; prior
CI cannot qualify this new source. No current35 compilation, ABI execution,
native artifact, full workflow or performance result is claimed here.

The 198-component Rust inventory and all 15 capability groups are unchanged:
13 remain pending and two remain partial. String utilities remains partial
with the new candidate; CLI/TUI remains pending. Whole production dispatch,
default release, workspace/product behavior, required platforms, independent
artifact custody, performance and legacy retirement remain unqualified.

## Earlier source increment: proposed plan parsing

The following is the preserved 34-module source-preparation record. Its
counts and pending gates describe that earlier increment; subsequent CI
observations remain bound to their own revisions and do not qualify Fuzzy35.

The complete `proposed_plan_parser` source unit moves line-based plan parsing
into HIA under the existing opt-in feature. HIA owns UTF-8 admission, the pinned
25 whitespace scalars, LF line decisions, both marker-prefix candidates,
normal/plan channels, pending counters, Start/End barriers and EOF reset.
Explicit continuation commands preserve segments across internal frames while
keeping distinct public calls separate.

The current source configures **34 modules and 31 opt-in caller kernels**:
32 borrowed-buffer and two unchanged scalar profiles. Seven Cargo build owners
account for the links (9 + 7 + 3 + 8 + 1 + 1 + 2). The stream-parser owner adds
its second link through the existing Core and CLI feature route. Installed CLI
admission requires 30 symbols, with one library-only and three retained
oracle-only modules kept distinct.

Kernel source origin: `da3817ebea57da1a940c12abc57999ce3d50706a`.
The [buffer contract](proposed_plan_parser_buffer_contract.json) binds the
complete source. Push, Finish and readonly Inspect use an 88-byte request
header and at most 4096 payload bytes, always ending at a complete UTF-8 scalar.
An 80-byte output header precedes 32-byte commands. Required capacities are
80 + 96*N, 176 and 80. The native wrapper's entire u64 result is checked before
interpreting its bounded Core u32 extent.

Rust retains the unbounded pending String and original segment Vec. It
validates every command and the complete returned state before applying a
frame's mechanical effects. The original `map_segments` runs exactly once
per public call. Inspect supplies the exact original Debug fields without
consuming pending input. The default parser and both generic parser tests
remain; original method bodies and the streaming/finalization order are
preserved.

The raw gate has 204 literal templates and 713 planned native invocations:
six streams with 532 calls plus 181 standalone cases. Two streams prescribe
257 chunks of 4096 whitespace bytes each. These are authored fixtures and do
not claim executed performance or a workload above 4 GiB. The corpus is below
the unchanged 512000-byte limit; no reference parser computed its expectations.

Five original ProposedPlan methods and two original generic methods are
preserved. Thirteen added public methods run under both feature selections.
Eleven native decoder methods check malformed frames and validation before
effects. Two additional native-only public witnesses exceed 1 MiB; matching
small literal cases cover the default path without claiming large default
execution. Existing complete owner, strict lint and eight Core consumer gates
cover the composition with Citation. Their commands and budgets remain intact.

Current raw gates select full-native34. Historical exact29/30/31/32/33 profiles
retain their closed module sets and defaults. Fresh B1/B2/B3, all 34 module
bindings and every static-link receipt are required. Earlier receipts cannot
qualify this source increment.

At source preparation, this increment was uncompiled and unexecuted. This
historical paragraph does not relabel later observed CI. Runtime, default
release, whole workspace/product, required platforms, performance, independent
artifact custody and retirement were not qualified by the source record; none
of its evidence is transferred to the current Fuzzy35 increment.

## Earlier source increment: citation streaming

The following 33-module description records the earlier source increment.
Its evidence is revision-bound and does not qualify the current 34-module tree.

The complete citation_stream_parser source unit moves the literal, non-nested
citation parser into HIA under the existing opt-in feature. HIA owns matching,
pending prefixes, body/visible events, citation completion and EOF reset.
Rust keeps owned containers and bounded transport. The original generic tag,
plan and UTF-8 admission parsers remain available for their original roles.

The current source configures **33 modules and 30 opt-in caller kernels**:
31 borrowed-buffer and two unchanged scalar profiles. Seven Cargo build
owners account for the links (9 + 7 + 3 + 8 + 1 + 1 + 1). The new owner is
codex-utils-stream-parser. Core forwards its existing hia-native feature to
that owner; the CLI already forwards Core, so no duplicate CLI route is added.
Installed CLI admission requires 29 symbols, with one library-only and three
retained oracle-only modules kept distinct.

Kernel source origin after the fixed-compiler result-count repair:
`20c7ce19ae5775c50e3999ba7fcca424939a8078`.
The [buffer contract](citation_stream_parser_buffer_contract.json) binds its
complete bytes. Push, Finish and readonly Inspect use a 40-byte request header
and at most 4096 payload bytes. HIA returns packed records after a 48-byte
header. The output reservations are 98 + 33*N, 98 and 64 + prefix respectively.
The finite state does not contain an aggregate body, text or citation limit.
Rust accumulates internal byte fragments before converting complete public
results to UTF-8. Inspect supplies pending bytes for the original compact and
alternate Debug structures without a second parser in Rust.

The raw gate has 230 literal templates and 742 planned native invocations:
13 streams with 558 calls plus 184 standalone frames. Two streams prescribe
257 chunks of 4096 bytes each; they are unexecuted source fixtures and do not
claim performance or a workload above 4 GiB. The corpus is below the unchanged
512000-byte repository limit. No reference parser computed its expectations.

All 15 original owner methods and eight selected Core streaming/finalization
methods are preserved. Ten added public tests cover per-call extraction,
empty/repeated finish and reuse, false prefixes, internal UTF-8 splits, many
citations, visible/body data above 1 MiB, and exact Debug continuity. The
workflow adds complete owner default/native tests, strict owner lint and
the eight original Core consumers in both configurations. Existing groups,
the complete historical job and both 60-minute budgets remain intact.

Network, output-lines, item-budget and environment raw gates explicitly select
full-native33; the new citation gate requires it. Historical exact29/30/31/32
profiles retain their original closed module sets and defaults. Fresh B1/B2/B3,
all33 module/artifact bindings and all seven-owner static-link receipts are
required; earlier receipts cannot qualify this source increment.

The source-preparation record for this earlier increment is retained here.
Later execution evidence applies only to its exact source revision. It does
not qualify the current increment, default release, complete workspace/product,
performance, independent artifact custody or retirement.

## Earlier source increment: bounded environment display

The complete format_env_display source unit is authored with a borrowed v8
HIA entry. HIA owns iterative heap sorting, byte comparison, masks, separators
and join progress. Rust retains owned containers, mechanical swaps, bounded
transport and complete-string UTF-8 validation. Map keys finish before each
variable's original AsRef call, once per variable; the final join follows all
variables. Empty and duplicate variable names remain observable. Map values
are not read, and there is no Rust sorting/comparison fallback.

The current configuration contains **32 modules and 29 opt-in caller kernels**:
30 borrowed-buffer profiles and the unchanged two scalar profiles. Six Cargo
build entries account for the links (9 + 7 + 3 + 8 + 1 + 1). The new owner is
codex-utils-cli; the CLI's two MCP views and the TUI's MCP environment view
continue to call its public function. These are source counts, not runtime
coverage or qualification claims.

The kernel's complete source origin is
917b786fbf6f0d25a19fe5748074f59f997e0e04. The
[buffer contract](format_env_display_buffer_contract.json) binds the exact
kernel bytes and five bounded operations. Chunks are at most 4096 bytes per
key; full key/output lengths are carried separately. This protocol avoids
using a single frame or the u32 status to bound the public function's output.
The configured seed-wrapper cap is not a claim that every B3 production path
has that cap.

The raw harness contains 231 authored literal frames: 71 calls in 22 complete
streams and 160 standalone cases. Ten cases use logical large lengths and do
not represent executed giant-payload workloads. The public source retains all
four original methods and five complete equalities, and adds nine methods,
including a comparison of two keys with a shared prefix over 1 MiB. No new
kernel, default/native public test or current32 build has been executed here.

The workflow retains all prior owner groups and selected Core methods. It
adds only the new raw gate and the new owner's default/native crate tests;
the existing four-owner and later consumer groups are not duplicated. The
network, output-lines and output-item-budget raw commands select full-native32;
the new environment raw gate requires it. Historical exact29/30/31 profiles
remain closed sets with their original defaults. Installed CLI checks require
28 linked symbols, plus one library-only and three retained oracle-only roles
with their existing distinctions.

Both workflow jobs retain their 60-minute budgets. Fresh B1/B2/B3, all32
module/artifact bindings, six-owner static links and complete original oracles
are pending. The workflow still has only original/current network baselines;
the separate mandatory original/native16/current gate remains unexecuted.
Earlier31/30/483 qualification records are preserved as historical objects.
Current runtime, default release, workspace, performance, independent artifact
custody and retirement flags remain false. The thirteen pending and two partial
capability groups are unchanged.

## Earlier source increment: output-item budget decisions

The authored `output_item_budget` module moves only numeric per-item budget
state and keep/omit/truncate decisions into HIA. Rust retains the original
item order, callback timing, text truncation, opaque content and omission
summaries. The current configuration has **31 modules and 28 opt-in caller
kernels**: 29 borrowed-buffer entries and the same two scalar entries. Five
Cargo build entries configure those links (9 + 7 + 3 + 8 + 1).

The new [buffer contract](output_item_budget_buffer_contract.json) binds the
kernel source bytes. Its raw harness contains 143 literal frames; eight new
public Rust tests and the original truncation tests exercise the same public
API in default and `hia-native` configurations. Two existing Core caller
oracles are also selected in both configurations. These are authored gates,
not execution results. Build, runtime, platform, performance, default-release,
whole-product and retirement qualification remain open or false.

The opt-in feature propagates from the CLI through `codex-core` to
`codex-utils-output-truncation` and the existing native string feature. The
default Rust implementation and all original budgets/oracles remain. Fresh
`full-native31` compiler generations and all31 source/object/library/archive/
link bindings are required; historical exact29/30 profiles remain distinct
and cannot admit the new kernel. The installed symbol check requires27 CLI
symbols, plus one library-only and three retained raw-only module identities;
symbol presence alone does not prove a budget call executed.

The current network-owner workflow still runs only `original` and `native31`.
The separate mandatory `original`/`native16`/`native31` owner gate requires its
admitted published16 bundle and is not satisfied by that workflow. The same
60-minute limits, compiler pin and complete exact74d1 historical job remain.
Kernel source origin: `3f18f08d19d59a49e2fbe19a85b306db14136abe` (source identity,
not an execution or publication claim).

## Earlier source increment: output line counting

The following section preserves the earlier30 source-increment record. Its
counts and unexecuted status describe that record, not current31 qualification.

The authored `output_lines` source connects through the existing `hia-native`
string feature. HIA owns LF counting, chunk state and final-line arithmetic;
the host retains fixed 4096-byte transport chunks and the original output
truncation order and budgets. The current configuration has **30 modules and
27 opt-in caller kernels**, including 28 borrowed-buffer and two scalar entries.
These are source counts, not a claim of a published release or successful build.

The raw ABI harness and Rust public-oracle sources are authored. Neither has
been executed for this increment. Current build, native/default public,
installed-consumer, artifact-custody and performance qualification remain open.
Fresh full-native30 compiler generations and all source/object/archive/link
receipts are required; earlier full-native29 reports cannot qualify this lock.
Kernel source: `8987467886706dfec8bfbd3e05f0f1f8ecbf965e`.

The current network-owner workflow compares `original` and `native30` only.
The separate mandatory owner gate requires `original`, `native16` and `native30`
with an admitted published16 link bundle. This workflow does not execute or
satisfy that three-baseline gate. Both original 60-minute job budgets, the
separate exact74d1 historical job, compiler pin, default Rust dispatch and all
whole-product/retirement flags remain unchanged.

The earlier revision records below are retained as historical evidence.
`verification.json` keeps their full build and qualification summaries separate
from current unqualified source, without relabeling old results.

## Earlier revision qualification

The joint source at `48324e2e75f2ebf46540e8db667b3f33fc7b3a7c` passed
[push run 43805537036](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43805537036),
attempt 1. Its current29 job and the separate exact74d1 historical job both
finished successfully within the original 60-minute budgets. The complete
original decoded logs and API metadata support this result. The two full
artifact ZIPs have **not** been independently downloaded or audited.

These results belong to that exact qualification revision and tree
`e96ac49ec70c97b7e5bd1938b060be65f094cb70`. They do not qualify later revisions.
Whole-product, default-release, complete workspace, platform, performance and
retirement qualification remain false.

## Subsequent revision evidence

Codex revision `2ab2266db6ae013f39f44e36cb062fbebb46b7c7` completed both
[push run 43816434217](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43816434217)
and
[PR run 43816440180](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43816440180),
attempt 1. Each current job completed 104 API steps, and each separate exact74d1
job completed 54. The PR actually checked out merge
`98f1cbc1930276a38cc5c93ca54158fb6d1267b3`, with the same source tree
`22737e49aa026118115e0a7a97ae4956d421eb65`. These native results preserve their
own logs and reports; they do not replace the 48324e evidence below. The general
[blocking workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43816440014)
failed. Source repairs in `8590718e50b8c2991e249988fe4467db989b22ba` and every
successor require their own checks.

Separately, Hepta revision `474aa8ccb94c1186afb8e4be4fd1217c43be4390` passed
[push run 43813432186](https://github.com/TrillionniumFoundation/Hepta/actions/runs/43813432186),
attempt 1, including the original source/native gates and the new selected
artifact export. Its
[PR run 43813438642](https://github.com/TrillionniumFoundation/Hepta/actions/runs/43813438642)
failed the original ordinary-caller timeout assertion: 5.8470409960000325
seconds against the unchanged 5-second bound. The PR had the same source tree,
with a different merge commit. This failure remains an open qualification
condition.

Selected push artifact `14204797010` was independently received in full:
12,806,029 bytes, SHA256
`09734e5d7a3d7005c3fef6e4ec924a77bb2272874d9c62f5f7ccc7a7adaa0a05`.
The data-only receiver verified all 464 member byte sequences, modes and hashes;
the 2,593-file current source tree; 960 cold-source identity records; 13 complete
compilation packets with their inputs, outputs and produced images; 38 phase
reports and archive manifests; and 17 reference families. Its complete result
has SHA256
`3579cff0f9b9d6b2930bb8a8bc6c710e726f832d845ea33738e621db8ee2aeb4`.
No delivered program was executed during this receiving step. The original
large artifact and omitted phase archive payloads remain outside independent
custody. This receipt is specific to the successful push and does not override
the PR failure, qualify product execution, or authorize A/B or retirement.
Codex retains compiler pin `0de5657a80f96b138525ac7ee9ce11712a83a10d`.

## Names and current callers

The tree composes the fixed `d2fb9ecd772da7736e973aaa3d90f14512dedddf`
nineteen-name branch with the HIA scope of
`74d1c0ebeced1b72a0ee74e375a0ace623762b01`, a historical union of 29 audited
names. The later source increments add `output_lines`, `output_item_budget`,
`format_env_display`, `citation_stream_parser`, `proposed_plan_parser` and
`fuzzy_match` for 35 modules. Eight Cargo build entries configure 32 opt-in links
(9 + 7 + 3 + 8 + 1 + 1 + 2 + 1) when
`hia-native` is enabled.
`utf8_boundaries`, `uuid_matches` and `template_parser` remain raw-oracle-only
kernels; their current production replacements are `utf8_prefix`, `uuid_find`
and `template_parse`. There are two scalar profiles, `token_budget` and
`prefix_admission`; the other 33 entries retain the borrowed
buffer profile. See `joint_module_roles.json` for source, role, replacement and
link sites. Names, configured links, algorithms and observed calls are distinct
counts.

The current template uses the v9 parse/render ABI with the original HIA Index
builder for placeholder storage. Kind-3 names keep their exact UTF-8 byte
ranges, HIA owns deduplication/order, and owned `Vec` storage preserves the
original ExactSizeIterator/drop behavior. The v9 render frame and private DTO
tests are not normalized. The default Rust implementation remains in place.

## Observed CI at 48324e (historical)

The current job completed **104 API steps** in 2,610 seconds; the historical
job completed **54 API steps** in 2,368 seconds. Both had zero failed or skipped
API steps. API steps are not test counts. The historical job actually checked
out exact `74d1c0ebeced1b72a0ee74e375a0ace623762b01`; its results do not qualify
the current ABI.

The current log records the full 29-module build with Hepta
`0de5657a80f96b138525ac7ee9ce11712a83a10d` and B1/B2/B3 fixed-point SHA256
`76fe758bc49499046169a5b4798c31d57366344c23530b35bc489e4008639273`.
Both scalar admission profiles passed 136 checks. Original public/raw gates,
installed consumers, strict checks and final maintenance also completed. This
is observed CI evidence; complete report and binary payload custody remains
pending. Fresh receipts cannot be relabeled for later source or lock changes.

The nine current nextest summaries are preserved separately:

| Original selection | Passed | Reported skipped or filtered |
| --- | ---: | ---: |
| apply-patch, utils-string, utils-template, execpolicy | 202 | 0 |
| output-truncation, protocol, context-fragments | 319 | 0 |
| CLI, arg0, TUI owners | 4,473 | 6 |
| Seven template owner/consumer packages, native | 387 | 0 |
| Same seven packages, default | 384 | 0 |
| Default production crates and truncation consumers | 504 | 0 |
| Filtered Core exec-policy integration | 11 | 3,870 |
| Filtered Core network-domain consumer | 1 | 3,880 |
| Filtered protocol allowed-prefix consumer | 1 | 300 |

These selections overlap and are **not added together**. The last three use
explicit filters; their reported skipped counts include unselected tests. The
CLI group retains its original six skips. This is not a complete workspace
qualification. Separate historical summaries were 198, 4,474 with six skips,
and 185; they are not current29 results.

The four corrected public differentials (`policy_summary`, `network_domains`,
`allowed_prefixes`, `command_dispatch`) each printed `passed: true` and an exact
report SHA. Their public comparison counts remain `null`: the complete report
payloads have not been read. `verification.json` records all four hashes and
keeps adjacent raw ABI call counts separate.

## Evidence and remaining limits

The original current decoded log is 2,138,385 bytes, SHA256
`18742a9e9da5517f1d7cdebe5aef1052a91216f9dc78176182b75a395a9c08c2`.
The original historical decoded log is 1,640,806 bytes, SHA256
`7d6b8b04e3020083fcb96a55bbb52df1f3b465f1dc338fd02c5bbb6f1ba38093`.
Their API references, exact checkouts, timestamps and nine test summaries are
recorded in `verification.json#ci_qualification_at_revision`.

Artifact `14200325804` is 142,198,783 bytes; historical artifact `14199372814`
is 20,570,859 bytes. Their API/upload digests are recorded, but both remain
**metadata-only**. Independent whole-ZIP SHA/CRC, member and source custody are
not complete. Earlier startup and wrapper failures remain recorded negatives;
this successful run does not rewrite those results.

The workflow retains its original current gates and separate historical ABI
job. The old shared `codex_hia_template_render` symbol uses a v8 40-byte command,
64-byte workspace, 32-byte output and success=32. The current v9 ABI uses a
>=64-byte frame, 32-byte workspace, 80-byte header and success=0. Historical raw
results must remain attached to their own library and checkout.

## Preserved behavior and retirement

Complete original oracles, payload/event order, source destruction, clone/drop,
callbacks, AsRef/value Drop faults, 100 raw private DTO frames, UUID public
harnesses, policy consumers and installed patch/CLI behaviors remain in the
workflow. Original metadata files under `history/` are unchanged.

All fifteen capability groups recorded in `migration.json` remain unclosed:
thirteen are pending and two retain `partial_opt_in_caller`. This registry is
not a complete inventory of the shared project. Required platforms and host
combinations,
complete workspace and product behavior, integrated performance, default
migration and independent artifact custody still need their own evidence.
Legacy removal requires a separately reviewed proposal after those conditions
are met. This change grants no retirement or A/B execution authority.
