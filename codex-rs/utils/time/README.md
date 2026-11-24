# Persisted time boundaries

This crate uses `time` for calendar validation and signed arithmetic and Jiff for
system/IANA time-zone lookup and display formatting. It replaces the workspace's
unmaintained date dependency without changing timestamp bytes in signed caches.

`Timestamp` keeps floor-based POSIX seconds and a nonnegative nanosecond field.
UTC serialization emits `Z` and the established zero, three, six, or nine
fractional digits. A represented leap second remains distinct from the following
minute; the UTC calendar range is -262143 through 262142. These choices are wire
contracts, including the bytes covered by the cloud-config cache HMAC.

Native clock reads retain `SystemTime`. Browser WebAssembly uses Jiff's `js`
clock, preserving the millisecond JavaScript clock previously enabled by OAuth's
time dependency; a direct `SystemTime::now()` would panic on that target. The
local qualification recorded here runs on native Linux, not in a browser.

`OffsetTimestamp` records whether its offset came from the system-local zone or
an explicit fixed offset. Arithmetic on a system-local value resolves the new
instant through the zone rules, including DST; fixed-offset arithmetic preserves
the fixed offset. `in_time_zone` returns a fixed-offset snapshot of an explicitly
supplied zone. `to_local` selects system-local behavior.

For expanded years outside Jiff's timestamp range, IANA lookup uses the initial
historical offset for the distant past and the Gregorian 400-year cycle of its
future POSIX rules. The qualified domain is the system/IANA database and fixed or
POSIX zones, not hypothetical TZif data with explicit transitions in those distant
sample years. The represented instant and formatted year are never replaced by
the sample instant.

The numeric calendar parser supports the `%Y`, `%m`, `%d`, `%H`, `%M`, and `%S`
directives used by rollout filenames and date windows. It preserves their
unpadded numeric fields and leap seconds. It is not a general strptime parser.
The explicit RFC 3339 parser remains stricter than persisted timestamp decoding;
persisted values also retain the previous component whitespace, `UTC`, expanded
year, and colon-free offset syntax.

Sibling tests cover persisted bytes, negative epochs, represented leap seconds,
numeric filename parsing, fixed-offset versus local DST arithmetic, and expanded
year display. Cloud-config tests pin six previous-version JSON payloads and HMAC
signatures. The old library is used only by an external differential oracle; it
is absent from this crate's runtime and test dependencies.
