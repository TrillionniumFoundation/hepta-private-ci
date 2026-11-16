# HIA components: joint source candidate

This tree composes the fixed `d2fb9ecd772da7736e973aaa3d90f14512dedddf`
nineteen-name branch with the HIA scope of
`74d1c0ebeced1b72a0ee74e375a0ace623762b01`. It is a **source-only candidate**:
the joint tree has not been built, formatted, tested or benchmarked. No default
production migration or legacy removal is claimed.

## Names and current callers

The lock contains 29 audited module names. The four actual Cargo build entries
link 26 kernels when `hia-native` is enabled. `utf8_boundaries`, `uuid_matches`
and `template_parser` remain raw-oracle-only kernels; their current production
replacements are `utf8_prefix`, `uuid_find` and `template_parse`, respectively.
There are two scalar profiles, `token_budget` and `prefix_admission`; the other
27 entries retain the borrowed-buffer profile. See `joint_module_roles.json`
for every source, role, replacement and current link site. Neither 29 names nor
26 configured links is a count of observed production calls or algorithms.

The current template uses the v9 parse/render ABI with the original HIA Index
builder for placeholder storage. Kind-3 names keep their exact UTF-8 byte
ranges, HIA owns deduplication/order, and owned `Vec` storage keeps the original
ExactSizeIterator/drop behavior. The v9 render frame and raw private DTO tests
are not normalized. The default Rust implementation remains in place.

## Rebuild and qualification obligations

`hia/build.py` and `hia/cargo_build.rs` are unchanged from both owners. The
complete lock has changed, so every native build report and 17-field `.link`
receipt must be regenerated and admitted; old owner artifacts are not relabeled
as current. The template Index admission binds its actual compiler input, raw
and namespaced objects, archive, shared library, source/contract and `.link`
before Cargo linkage. Network-host admission requires `full-native29`, all 29
artifacts, both scalar profiles and three fixed-point generation identities.
The current workflow does not use the local-incremental path.

The workflow retains all head19 gates, adds the original execpolicy/Index and
compatibility gates, and retains each original strict check and source inverse.
It separately runs the complete exact74d1 workflow under `historical-native17`.
That job is necessary because the old shared `codex_hia_template_render` symbol
uses a v8 40-byte command, 64-byte workspace, 32-byte output and success=32;
the current v9 ABI uses a >=64-byte frame, 32-byte workspace, 80-byte header and
success=0. Old raw results must never be attributed to the current library.

Both jobs keep their original 60-minute budget. The additional joint cost and
the ability to finish all current gates within that budget are **unverified**.
Report filenames and artifact names separate current, compatibility and exact
historical evidence. This source candidate does not increase a timeout, add a
retry, skip an oracle, or treat historical success as a current pass.

## Preserved behavior and retirement

The complete original oracles remain: template case pairs and constructors,
full payload and event order, source destruction, clone/drop, exact callbacks,
AsRef/value Drop faults, the 100 raw private DTO frames, both UUID public
harnesses, original policy consumers and installed patch/CLI behaviors. Source
inverses recover their complete fixed original files rather than extracted
semantic functions. Metadata histories under `history/` retain both owner's
original records byte-for-byte, with their exact commits and hashes.

Retiring any old kernel requires fresh complete joint-build/source/receipt
qualification, all public and raw contracts (including errors and effects),
all supported platforms and installed consumers, and a separately reviewed
removal. No such removal is part of this candidate. All fifteen capability
groups remain unclosed: thirteen are pending and two retain their
partial_opt_in_caller status. Whole-product, default-release, workspace,
performance and retirement claims remain false. `verification.json` contains only current
unexecuted obligations and links to explicitly historical evidence.
