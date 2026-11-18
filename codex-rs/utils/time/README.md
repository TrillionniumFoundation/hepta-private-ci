# UTC timestamps and stable wire values

This crate supplies the shared UTC codec for replacing the previous timestamp dependency.
It uses `time::OffsetDateTime` for ordinary instants and keeps the existing wire spelling,
fraction precision, negative epoch rounding, and supported year range explicit.

## Ordinary instants

`from_unix_parts` and `from_unix_millis` preserve floor-based epoch semantics.
For example, `1969-12-31T23:59:59.999999999Z` has second `-1` and millisecond `-1`.
Use `unix_millis_floor` when writing persisted milliseconds; truncating a signed duration
toward zero would produce a different value before the epoch.

`format_rfc3339_utc` always normalizes the supplied offset to UTC. `Precision::AutoSi`
emits zero, three, six, or nine fractional digits. Fixed precision truncates without
rounding. `UtcSuffix` chooses `Z` or `+00:00` explicitly.

The ordinary RFC 3339 parser preserves the previous strict parser's accepted syntax.
The serde adapters preserve the previous, more permissive serde grammar, including
signed extended years, short numeric components, surrounding whitespace, and `UTC`.
Both discard fractional digits after the ninth, matching the previous parser.

The supported range remains years -262143 through +262142 after UTC conversion.
The `large-dates` dependency feature is explicit; the codec does not depend on another
workspace crate accidentally enabling it.

## Authenticated cache values and leap seconds

`CanonicalUtcTimestamp` preserves the previous canonical UTC serialization, including
an explicit `:60` leap second. It retains the canonical value, not the original input
spelling. Reserializing a value that originally contained an offset therefore still
produces exactly the previous UTC representation.

`try_into_instant` returns `UnrepresentableLeapSecond` for a leap second. The ordinary
parser and instant serde adapters return an error as well. They never normalize the
input to the following second or replace it with the last nanosecond of `:59`.

For historical log rows, `CanonicalUtcTimestamp::from_unix_parts` accepts the previous
explicit leap representation. Its `format` method preserves fixed millisecond or
microsecond output, including `:60`. The ordinary `from_unix_parts` function continues
to reject leap seconds, and no arithmetic API is added to the carrier.

Existing expiry comparisons can use `compare_to_instant`. It preserves the previous
lexicographic comparison of epoch seconds and subsecond nanoseconds. A leap second
sorts after every ordinary fraction of its preceding second and before the following
second. It must not be converted to a total nanosecond count for that comparison.
The carrier intentionally has no general `Ord`, subtraction, or duration API.

## Verification

The three JSON oracle fixtures are retained byte-for-byte from the earlier migration
component `699d8258a1929b12a597b201778e50842ce4e83f`. The predecessor records their
generation with Chrono 0.4.45, serde 1.0.229 and serde_json 1.0.154. Their original
SHA-256 values are fixed in the joint candidate's
`qualification/chrono-cloud-cache-joint-20261118/ORIGIN.json`.

The product crate and its tests do not add a Chrono dependency. The joint candidate
runs the codec fixture regressions and the complete cloud-config package tests on
its own source and dependency locks. Historical predecessor test counts do not
qualify this source. Run these scoped regressions with
`just test -p codex-utils-time -p codex-cloud-config`.
