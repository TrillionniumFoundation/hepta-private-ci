# HIA components: revision-bound joint qualification

## Current source increment: output line counting

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
names. The current lock adds `output_lines` for 30 modules. Four Cargo build
entries configure 27 opt-in links (9 + 7 + 3 + 8) when `hia-native` is enabled.
`utf8_boundaries`, `uuid_matches` and `template_parser` remain raw-oracle-only
kernels; their current production replacements are `utf8_prefix`, `uuid_find`
and `template_parse`. There are two scalar profiles, `token_budget` and
`prefix_admission`; the other 28 entries retain the borrowed
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
