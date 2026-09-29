use std::cell::Cell;
use std::error::Error;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use codex_hepta_contracts::FinalUseRevocations;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn head(epoch: u64, revision: u64, revoked: &[&str]) -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: epoch,
        revision,
        revoked_grant_ids: revoked.iter().map(|value| (*value).to_string()).collect(),
    }
}

fn private_directory() -> TestResult<TempDir> {
    let directory = TempDir::new()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    Ok(directory)
}

fn write_private_json(path: &Path, value: &FinalUseRevocations) -> TestResult {
    std::fs::write(path, serde_json::to_vec(value)?)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(())
}

fn replace_private_json(path: &Path, value: &FinalUseRevocations) -> TestResult {
    let replacement = path.with_extension("replacement");
    write_private_json(&replacement, value)?;
    std::fs::rename(replacement, path)?;
    Ok(())
}

#[test]
fn unchanged_feed_skips_semantic_revalidation() -> TestResult {
    let directory = private_directory()?;
    let path = directory.path().canonicalize()?.join("revocations.json");
    let expected = head(17, 1, &[]);
    write_private_json(&path, &expected)?;

    let (feed, observed) = RevocationFeed::open(path, 4096)?;
    assert_eq!(observed, expected);
    let called = Cell::new(false);
    feed.refresh(|_| {
        called.set(true);
        Ok(())
    })?;
    assert!(!called.get());
    Ok(())
}

#[test]
fn changed_feed_is_applied_once_then_returns_to_fast_path() -> TestResult {
    let directory = private_directory()?;
    let path = directory.path().canonicalize()?.join("revocations.json");
    let initial = head(17, 1, &[]);
    let expected = head(17, 2, &["revoked-a"]);
    write_private_json(&path, &initial)?;
    let (feed, observed) = RevocationFeed::open(path.clone(), 4096)?;
    assert_eq!(observed, initial);

    replace_private_json(&path, &expected)?;
    let calls = Cell::new(0_u64);
    feed.refresh(|observed| {
        calls.set(calls.get() + 1);
        assert_eq!(observed, expected);
        Ok(())
    })?;
    feed.refresh(|_| {
        calls.set(calls.get() + 1);
        Ok(())
    })?;
    assert_eq!(calls.get(), 1);
    Ok(())
}

#[test]
fn in_place_rewrite_fails_closed() -> TestResult {
    let directory = private_directory()?;
    let path = directory.path().canonicalize()?.join("revocations.json");
    let initial = head(17, 1, &[]);
    let rewritten = head(17, 2, &["revoked-with-a-longer-identity"]);
    write_private_json(&path, &initial)?;
    let (feed, observed) = RevocationFeed::open(path.clone(), 4096)?;
    assert_eq!(observed, initial);

    write_private_json(&path, &rewritten)?;
    let called = Cell::new(false);
    assert_eq!(
        feed.refresh(|_| {
            called.set(true);
            Ok(())
        }),
        Err(MatrixAuthorityError::Unavailable),
    );
    assert!(!called.get());
    Ok(())
}

#[test]
fn rejected_feed_identity_is_not_cached() -> TestResult {
    let directory = private_directory()?;
    let path = directory.path().canonicalize()?.join("revocations.json");
    let initial = head(17, 3, &["revoked-a"]);
    let rejected = head(17, 2, &[]);
    write_private_json(&path, &initial)?;
    let (feed, observed) = RevocationFeed::open(path.clone(), 4096)?;
    assert_eq!(observed, initial);

    replace_private_json(&path, &rejected)?;
    let calls = Cell::new(0_u64);
    for _ in 0..2 {
        assert_eq!(
            feed.refresh(|observed| {
                calls.set(calls.get() + 1);
                assert_eq!(observed, rejected);
                Err(MatrixAuthorityError::Rejected)
            }),
            Err(MatrixAuthorityError::Rejected),
        );
    }
    assert_eq!(calls.get(), 2);
    Ok(())
}
