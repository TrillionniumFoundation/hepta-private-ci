use crate::SqliteConfig;
use crate::model::epoch_millis_to_datetime;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

type ScalarRow = (
    i64,
    i64,
    i64,
    i64,
    Option<i64>,
    String,
    String,
    String,
    String,
);

#[tokio::test]
async fn scalar_sqlite_values_keep_types_nulls_and_reopen() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    std::fs::create_dir(&home)?;
    let home = scopeguard::guard(home, |home| {
        let _ = std::fs::remove_dir_all(home);
    });
    let canonical_home = home.canonicalize()?;
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(canonical_home.clone())?);
    let path = canonical_home.join("scalar-temporal-contract.sqlite3");
    let pool = sqlite.open_read_write_pool(&path).await?;
    let fixtures: [(i64, i64, i64, i64, Option<i64>); 5] = [
        (1, -1, -1_001, -1_000_000_001, None),
        (2, 0, 0, 0, Some(0)),
        (
            3,
            1_700_000_000,
            1_700_000_000_123,
            1_700_000_000_123_456_789,
            Some(1_700_000_000_123),
        ),
        (4, i64::MIN, i64::MIN, i64::MIN, Some(i64::MAX)),
        (5, i64::MAX, i64::MAX, i64::MAX, Some(i64::MIN)),
    ];
    let query = "SELECT ordinal, seconds, milliseconds, nanoseconds, nullable_milliseconds, \
                 typeof(seconds), typeof(milliseconds), typeof(nanoseconds), \
                 typeof(nullable_milliseconds) FROM temporal_scalars ORDER BY ordinal";
    let initial: Result<Vec<ScalarRow>, sqlx::Error> = async {
        sqlx::query(
            "CREATE TABLE temporal_scalars (\
             ordinal INTEGER PRIMARY KEY, seconds INTEGER NOT NULL, \
             milliseconds INTEGER NOT NULL, nanoseconds INTEGER NOT NULL, \
             nullable_milliseconds INTEGER)",
        )
        .execute(&pool)
        .await?;
        for (ordinal, seconds, milliseconds, nanoseconds, nullable_milliseconds) in fixtures {
            sqlx::query("INSERT INTO temporal_scalars VALUES (?, ?, ?, ?, ?)")
                .bind(ordinal)
                .bind(seconds)
                .bind(milliseconds)
                .bind(nanoseconds)
                .bind(nullable_milliseconds)
                .execute(&pool)
                .await?;
        }
        sqlx::query_as(query).fetch_all(&pool).await
    }
    .await;
    pool.close().await;
    let initial = initial?;

    let read_only = sqlite.open_read_only_pool(&path).await?;
    let reopened: Result<Vec<ScalarRow>, sqlx::Error> =
        sqlx::query_as(query).fetch_all(&read_only).await;
    read_only.close().await;
    let expected: Vec<ScalarRow> = vec![
        (
            1,
            -1,
            -1_001,
            -1_000_000_001,
            None,
            "integer".to_owned(),
            "integer".to_owned(),
            "integer".to_owned(),
            "null".to_owned(),
        ),
        (
            2,
            0,
            0,
            0,
            Some(0),
            "integer".to_owned(),
            "integer".to_owned(),
            "integer".to_owned(),
            "integer".to_owned(),
        ),
        (
            3,
            1_700_000_000,
            1_700_000_000_123,
            1_700_000_000_123_456_789,
            Some(1_700_000_000_123),
            "integer".to_owned(),
            "integer".to_owned(),
            "integer".to_owned(),
            "integer".to_owned(),
        ),
        (
            4,
            i64::MIN,
            i64::MIN,
            i64::MIN,
            Some(i64::MAX),
            "integer".to_owned(),
            "integer".to_owned(),
            "integer".to_owned(),
            "integer".to_owned(),
        ),
        (
            5,
            i64::MAX,
            i64::MAX,
            i64::MAX,
            Some(i64::MIN),
            "integer".to_owned(),
            "integer".to_owned(),
            "integer".to_owned(),
            "integer".to_owned(),
        ),
    ];
    assert_eq!(initial, expected);
    assert_eq!(reopened?, expected);
    Ok(())
}

#[tokio::test]
async fn legacy_integer_rows_keep_original_conversion_and_refusal() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    std::fs::create_dir(&home)?;
    let home = scopeguard::guard(home, |home| {
        let _ = std::fs::remove_dir_all(home);
    });
    let canonical_home = home.canonicalize()?;
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(canonical_home.clone())?);
    let pool = sqlite
        .open_read_write_pool(&canonical_home.join("legacy-temporal-contract.sqlite3"))
        .await?;
    let fixtures: [(i64, Option<i64>); 9] = [
        (1, Some(-1)),
        (2, Some(0)),
        (3, Some(1_700_000_000)),
        (4, Some(1_577_836_799_999)),
        (5, Some(1_577_836_800_000)),
        (6, Some(1_700_001_111_123)),
        (7, Some(i64::MIN)),
        (8, Some(i64::MAX)),
        (9, None),
    ];
    let rows: Result<Vec<(i64, Option<i64>, String)>, sqlx::Error> = async {
        sqlx::query(
            "CREATE TABLE legacy_temporal_values (ordinal INTEGER PRIMARY KEY, value INTEGER)",
        )
        .execute(&pool)
        .await?;
        for (ordinal, value) in fixtures {
            sqlx::query("INSERT INTO legacy_temporal_values VALUES (?, ?)")
                .bind(ordinal)
                .bind(value)
                .execute(&pool)
                .await?;
        }
        sqlx::query_as(
            "SELECT ordinal, value, typeof(value) FROM legacy_temporal_values ORDER BY ordinal",
        )
        .fetch_all(&pool)
        .await
    }
    .await;
    pool.close().await;
    let rows = rows?;
    assert_eq!(
        rows,
        vec![
            (1, Some(-1), "integer".to_owned()),
            (2, Some(0), "integer".to_owned()),
            (3, Some(1_700_000_000), "integer".to_owned()),
            (4, Some(1_577_836_799_999), "integer".to_owned()),
            (5, Some(1_577_836_800_000), "integer".to_owned()),
            (6, Some(1_700_001_111_123), "integer".to_owned()),
            (7, Some(i64::MIN), "integer".to_owned()),
            (8, Some(i64::MAX), "integer".to_owned()),
            (9, None, "null".to_owned()),
        ],
    );
    // These are original converter outcomes, including its pre-2020 legacy
    // heuristic. Removing an optional SQLx codec must not silently revise them.
    let converted: Vec<(i64, Result<Option<i64>, String>)> = rows
        .into_iter()
        .map(|(ordinal, value, _)| {
            let outcome = value
                .map(epoch_millis_to_datetime)
                .transpose()
                .map(|value| value.map(|value| value.timestamp_millis()))
                .map_err(|error| error.to_string());
            (ordinal, outcome)
        })
        .collect();
    assert_eq!(
        converted,
        vec![
            (1, Ok(Some(-1_000))),
            (2, Ok(Some(0))),
            (3, Ok(Some(1_700_000_000_000))),
            (4, Ok(Some(1_577_836_799_999_000))),
            (5, Ok(Some(1_577_836_800_000))),
            (6, Ok(Some(1_700_001_111_123))),
            (
                7,
                Err("invalid unix timestamp millis: -9223372036854775808".to_owned())
            ),
            (
                8,
                Err("invalid unix timestamp millis: 9223372036854775807".to_owned())
            ),
            (9, Ok(None)),
        ],
    );
    Ok(())
}
