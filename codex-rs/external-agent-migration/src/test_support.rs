use time::OffsetDateTime;
use time::format_description::well_known::Rfc3339;

pub(crate) fn now_rfc3339_seconds() -> String {
    OffsetDateTime::now_utc()
        .replace_nanosecond(0)
        .expect("zero nanoseconds is valid")
        .format(&Rfc3339)
        .expect("current UTC time should be representable as RFC3339")
}
