use chrono::DateTime;
use chrono::Utc;

fn require_sqlite_type<T: sqlx::Type<sqlx::Sqlite>>() {}

fn main() {
    require_sqlite_type::<DateTime<Utc>>();
}
