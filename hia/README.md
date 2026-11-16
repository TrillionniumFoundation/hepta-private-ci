# HIA components: revision-bound joint qualification

The joint source at `48324e2e75f2ebf46540e8db667b3f33fc7b3a7c` passed
[push run 43805537036](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43805537036),
attempt 1. Its current29 job and the separate exact74d1 historical job both
finished successfully within the original 60-minute budgets. The complete
original decoded logs and API metadata support this result. The two full
artifact ZIPs have **not** been independently downloaded or audited.

These results belong to that exact qualification revision and tree
`e96ac49ec70c97b7e5bd1938b060be65f094cb70`. This documentation successor has no
new exact-head CI result. Whole-product, default-release, complete workspace,
platform, performance and retirement qualification remain false.

## Names and current callers

The tree composes the fixed `d2fb9ecd772da7736e973aaa3d90f14512dedddf`
nineteen-name branch with the HIA scope of
`74d1c0ebeced1b72a0ee74e375a0ace623762b01`. Its lock contains 29 audited module
names. Four actual Cargo build entries link 26 kernels when `hia-native` is
enabled. `utf8_boundaries`, `uuid_matches` and `template_parser` remain
raw-oracle-only kernels; their current production replacements are
`utf8_prefix`, `uuid_find` and `template_parse`. There are two scalar profiles,
`token_budget` and `prefix_admission`; the other 27 entries retain the borrowed
buffer profile. See `joint_module_roles.json` for source, role, replacement and
link sites. Names, configured links, algorithms and observed calls are distinct
counts.

The current template uses the v9 parse/render ABI with the original HIA Index
builder for placeholder storage. Kind-3 names keep their exact UTF-8 byte
ranges, HIA owns deduplication/order, and owned `Vec` storage preserves the
original ExactSizeIterator/drop behavior. The v9 render frame and private DTO
tests are not normalized. The default Rust implementation remains in place.

## Observed CI scope

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

All fifteen capability groups remain unclosed: thirteen are pending and two
retain `partial_opt_in_caller`. Required platforms and host combinations,
complete workspace and product behavior, integrated performance, default
migration and independent artifact custody still need their own evidence.
Legacy removal requires a separately reviewed proposal after those conditions
are met. This change grants no retirement or A/B execution authority.
