use std::error::Error;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::LockedFileProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::Args;
use super::digest;
use super::run_profile;

static NEXT_ROOT: AtomicU64 = AtomicU64::new(0);

struct ProfileRoot(PathBuf);

impl ProfileRoot {
    fn new() -> Result<Self, std::io::Error> {
        for _ in 0..16 {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos();
            let root = std::env::temp_dir().join(format!(
                "hepta-profile-test-{}-{nonce}-{}",
                std::process::id(),
                NEXT_ROOT.fetch_add(/*val*/ 1, Ordering::Relaxed)
            ));
            match fs::create_dir(&root) {
                Ok(()) => return Ok(Self(root)),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(error),
            }
        }
        Err(std::io::ErrorKind::AlreadyExists.into())
    }
}

impl Drop for ProfileRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn report_number(report: &str, field: &str) -> Result<u64, Box<dyn Error>> {
    let prefix = format!("\"{field}\": ");
    let value = report
        .lines()
        .find_map(|line| line.trim().strip_prefix(&prefix))
        .ok_or("missing profile number")?;
    Ok(value.trim_end_matches(',').parse()?)
}

#[test]
fn profile_report_binds_real_nonempty_seven_phase_storage_and_reopen() -> Result<(), Box<dyn Error>>
{
    for (attempts, fences) in [(1, 1), (3, 4)] {
        let root = ProfileRoot::new()?;
        let args = Args {
            attempts,
            fences,
            output: None,
        };
        let report = run_profile(&root.0, &args)?;
        let attempt_path = root.0.join("attempt.journal");
        let mut journal = LockedFileProductEvaluationAttemptJournalV1::recover(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&attempt_path)?,
            digest("profile-attempt-binding"),
        )?;
        let event_count = u64::try_from(journal.event_count())?;
        assert_eq!(event_count, attempts * 7);
        assert_eq!(journal.pending(/*after*/ None, /*limit*/ 1)?, Vec::new());
        assert_eq!(report_number(&report, "attemptCount")?, attempts);
        assert_eq!(report_number(&report, "eventCount")?, event_count);
        assert_eq!(
            report_number(&report, "bytes")?,
            fs::metadata(&attempt_path)?.len()
        );
        assert_eq!(report_number(&report, "fenceTransitions")?, fences);
        assert_eq!(report_number(&report, "planRecords")?, fences);
        assert_eq!(
            report_number(&report, "beforeBytes")?,
            fs::metadata(root.0.join("holdout.cas"))?.len()
        );
        assert_eq!(
            report_number(&report, "afterBytes")?,
            fs::metadata(root.0.join("holdout.compacted.cas"))?.len()
        );
        let (body, footer) = report
            .rsplit_once(",\n  \"profileDigest\": \"")
            .ok_or("missing profile digest")?;
        let actual_digest = footer
            .strip_suffix("\"\n}\n")
            .ok_or("invalid profile digest footer")?;
        let original_body = format!("{body}\n}}");
        assert_eq!(
            actual_digest,
            Digest32::of_bytes(original_body.as_bytes()).to_string()
        );
    }
    Ok(())
}

#[test]
fn profile_rejects_existing_inputs_before_replacing_history() -> Result<(), Box<dyn Error>> {
    let root = ProfileRoot::new()?;
    let path = root.0.join("attempt.journal");
    let history = b"independently retained previous attempt bytes";
    fs::write(&path, history)?;
    let result = run_profile(
        &root.0,
        &Args {
            attempts: 1,
            fences: 1,
            output: None,
        },
    );
    let error = match result {
        Err(error) => error,
        Ok(_) => panic!("profile replaced an existing attempt journal"),
    };
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .map(std::io::Error::kind),
        Some(std::io::ErrorKind::AlreadyExists)
    );
    assert_eq!(fs::read(&path)?, history);
    assert!(!root.0.join("holdout.cas").exists());
    assert!(!root.0.join("holdout.compacted.cas").exists());
    Ok(())
}
