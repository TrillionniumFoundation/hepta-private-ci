use std::fs;
use std::time::Duration;
use std::time::SystemTime;

use pretty_assertions::assert_eq;

use super::create_fake_rollout;
use super::rollout_path;

#[test]
fn fake_rollout_modification_time_preserves_signed_fractional_and_leap_seconds()
-> anyhow::Result<()> {
    let home = tempfile::tempdir()?;
    for (filename_ts, meta_rfc3339, expected) in [
        (
            "1970-01-01T00-00-00",
            "1970-01-01T00:00:00.500Z",
            SystemTime::UNIX_EPOCH + Duration::from_millis(/*millis*/ 500),
        ),
        (
            "1969-12-31T23-59-59",
            "1969-12-31T23:59:59.500Z",
            SystemTime::UNIX_EPOCH - Duration::from_millis(/*millis*/ 500),
        ),
        (
            "2016-12-31T23-59-60",
            "2016-12-31T23:59:60.500Z",
            SystemTime::UNIX_EPOCH + Duration::from_millis(/*millis*/ 1_483_228_800_500),
        ),
    ] {
        let id = create_fake_rollout(
            home.path(),
            filename_ts,
            meta_rfc3339,
            "fixture",
            /*model_provider*/ None,
            /*git_info*/ None,
        )?;
        assert_eq!(
            fs::metadata(rollout_path(home.path(), filename_ts, &id))?.modified()?,
            expected,
            "{meta_rfc3339}",
        );
    }
    Ok(())
}
