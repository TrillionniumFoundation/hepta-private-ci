# Rama time dependency qualification

This change removes the unconditional Chrono dependency from the two actual
`rama-http` and `rama-http-headers` 0.3.0-alpha.4 packages used by the network
proxy. It preserves the existing Rama service interfaces and package identities.
It does not upgrade the entire proxy to Rama 0.4's different service architecture.

## Sources and scope

Both official 0.3.0-alpha.4 crate archives were checked against the SHA-256
checksums in the integration Cargo lock before extraction. The separate import
commit contains the original files. Each package's `HEPTA-UPSTREAM-PINS.json`
records the archive checksum, original VCS commit and every original file hash.
Original `Cargo.toml.orig` and crate-local lock files remain provenance material;
the root workspace manifest and root Cargo lock determine the integrated graph.

The upstream maintained-time migration is
[plabayo/rama 3bc53326ad24b747eec1d7ec416f2ad95f0b4f7f](https://github.com/plabayo/rama/commit/3bc53326ad24b747eec1d7ec416f2ad95f0b4f7f).
It changes exactly four runtime files: the crawler expiry parser, HAR service,
HAR data types and directory-listing date formatter. This backport changes the
same four files plus their dependency manifests and build descriptions. The
older Rama error API remains `OpaqueError`; later error-context APIs are not
imported with an unrelated Rama upgrade.

## Compatibility adaptations

The official patch originally used Jiff 0.2 APIs. This integration uses the
maintained Jiff 1.0.3/calendar boundary already selected for the first-party
migration. The distinct `codex-utils-time::Timestamp` implementation uses `time`
for calendar arithmetic and Jiff for zones/formatting; it is not an alias for
Chrono and does not retain a hidden Chrono dependency.

- HAR page/entry/cache timestamps retain their numeric `+00:00` offset and
  established 3/6/9-digit fractional groups. Cookie timestamps retain the separate
  Serde `Z` convention. Negative epochs and represented leap seconds remain
  distinguishable. The old explicit RFC 3339 parser's input range is preserved.
- Crawler timestamp construction remains fallible for invalid calendar fields.
  Its established extended year range is retained, rather than inheriting the
  narrower Jiff constructor or the upstream infallible `civil::date` panic.
- The upstream RFC 850 offset correction is intentional: a local wall time with
  PST is converted to the corresponding UTC instant. Formatted RFC 850 values
  include `GMT`; date-only ISO input and formerly malformed negative timezone
  table entries follow the upstream acceptance changes. This parser is therefore
  not described as identical to every legacy behavior.
- Parsed `:60` values retain represented leap seconds after Jiff validates and
  normalizes the calendar fields. Conversion from Jiff uses floor division of
  total nanoseconds, including dates before the epoch.
- The directory listing uses the same maintained system-zone boundary as other
  consumers. The proxy's enforcement and connection logic are unchanged.

The vendor's public date accessor now returns the maintained timestamp type.
There is no claim of source compatibility for an arbitrary external caller that
explicitly expected `chrono::DateTime`. Repository references were checked; the
first-party proxy has no such dependency. Tests exercise the concrete new API.

## Qualification boundary

`codex-network-proxy/src/time_dependency_tests.rs` exercises the actual patched
Rama types, including HAR wire round trips, invalid calendar rejection, extended
year construction, represented leap seconds, and corrected timezone conversion.
The ordinary Linux `network-time-boundaries` job runs the entire network-proxy
library suite with the integration lock. It does not replace the full blocking CI.

At source preparation, Cargo 1.96 metadata resolved the two path patches and
repository formatting completed. A real integrated network library check was
interrupted with exit 130 when the shared temporary filesystem had 6.9 MiB free;
reusing an isolated oracle cache did not avoid the integration graph rebuild. No
tests executed and no compiler success is claimed for that attempt. These facts
do not establish that the new network test binary compiled or executed. Runtime qualification requires the
exact integration head's normal CI result. No advisory exception or required
assertion is removed by this backport.
