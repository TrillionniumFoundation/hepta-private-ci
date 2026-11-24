# Maintained timestamp boundary patch

Source: the published crates.io `rmcp-3.9.0` archive, SHA-256
`d24a7e92f4bcaa36b97fa93c4fa7ca8f3e669eced949345b3462dba333c7f909`. The original dual MIT/Apache licenses and upstream
source attribution are retained. Rust source is normalized with the repository
formatter; this is not a different upstream release.

The upstream migration proposal is https://github.com/modelcontextprotocol/rust-sdk/pull/1474 (9043cdfa8694d83bf506c2f3eb0313ec173edd7e).
It was open and unmerged when reviewed on 2026-11-24. This local backport removes
chrono, which has no patched version for
[RUSTSEC-2026-0543](https://rustsec.org/advisories/RUSTSEC-2026-0543.html).

This patch uses `codex-utils-time`, whose calendar/arithmetic implementation is
`time` and whose system/IANA time-zone implementation is Jiff. It contains no
chrono dependency or chrono API alias. Unlike a direct Jiff Timestamp conversion,
this keeps floor-based negative epoch seconds, represented leap seconds, the
existing wide civil range, and RFC 3339 fraction widths.

The typed Rust timestamp parameters now use `codex_utils_time::Timestamp`. This
is an intentional source API change confined to this repository's dependency
graph, not a claim of upstream semver compatibility. Protocol fields keep their
existing JSON representation. The repository's Rust 1.96 toolchain is required.

Clock reads, annotation builders, task metadata, and request-state milliseconds
use the shared boundary. `Annotations::for_resource`, `with_timestamp`, and
`with_timestamp_now` remain available; no feature disables them. The unused
`schemars/chrono04` enablement is removed because the timestamp field is a String.

The ISO duration formatter is adapted from upstream #1474 and retains the
existing `PT...S` diagnostic, `P0D` for zero, and `P0D` overflow fallback above
i64::MAX milliseconds. This patch keeps the published 3.9.0 protocol behavior;
it does not bring in unrelated changes from the upstream main branch.

Sibling regression tests pin the affected byte and boundary behavior. The
application's full lockfile, dependency advisory, Cargo consumer, and Bazel gates
remain necessary; compiling only these helpers is not a complete qualification.

Local source qualification (Rust 1.96): 336 library tests passed through an
external manifest loading these actual source files (client, server, schemars, request-state, macros). The
external old/new protocol oracle pinned chrono 0.4.43 and compared 120 OAuth
integer timestamp payloads, 120 MCP annotation payloads, 16 accepted/rejected
input boundaries, and 9 timeout messages with zero differences. An additional
0.4.45 legacy reference run is recorded separately. This checks the time boundary,
not the whole historical Cargo lock or all application consumers.
