use chrono::DateTime;
use chrono::Utc;

fn require_sqlite_codec<T>()
where
    T: sqlx::Type<sqlx::Sqlite>,
    for<'query> T: sqlx::Encode<'query, sqlx::Sqlite>,
    for<'row> T: sqlx::Decode<'row, sqlx::Sqlite>,
{
}

fn main() {
    require_sqlite_codec::<DateTime<Utc>>();
}
