# Maintained timestamp boundary patch

Source: the published crates.io `oauth2-5.0.0` archive, SHA-256
`51e219e79014df21a225b1860a479e2dcd7cbd9130f4defd4bd0e191ea31d67d`. The original dual MIT/Apache licenses and upstream
source attribution are retained. Rust source is normalized with the repository
formatter; this is not a different upstream release.

The upstream migration proposal is https://github.com/ramosbugs/oauth2-rs/pull/355 (e58e7c2d2b889b45e51f844247c3281e7a2f8f86).
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

Only device-polling clock/deadline arithmetic and introspection timestamp types
change. The integer `exp`, `iat`, and `nbf` serde adapter preserves omission, null,
range validation, and floor rounding. The prior device timeout duration limit and
legacy conversion diagnostic are retained. OAuth endpoint selection, HTTP, token
handling, polling state transitions, and request bodies are unchanged.

Compared with upstream #355, the qualified compatibility boundary replaces raw
Jiff serde because negative fractional seconds and years outside Jiff's range
otherwise change behavior. A subsecond value still serializes to whole seconds.

Sibling regression tests pin the affected byte and boundary behavior. The
application's full lockfile, dependency advisory, Cargo consumer, and Bazel gates
remain necessary; compiling only these helpers is not a complete qualification.

Rust 1.96 also requires explicit elided lifetimes in ten existing client return
types to avoid the new default warning. Only lifetime spelling changes there.

Local source qualification (Rust 1.96): 69 library tests passed through an
external manifest loading these actual source files (no default HTTP backend). The
external old/new protocol oracle pinned chrono 0.4.43 and compared 120 OAuth
integer timestamp payloads, 120 MCP annotation payloads, 16 accepted/rejected
input boundaries, and 9 timeout messages with zero differences. An additional
0.4.45 legacy reference run is recorded separately. This checks the time boundary,
not the whole historical Cargo lock or all application consumers.
