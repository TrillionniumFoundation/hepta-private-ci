use super::read_cap_sid_for_root;
use crate::token::LocalSid;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::path::PathBuf;

#[test]
fn canonical_read_roots_share_only_their_own_capability() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let first = temp.path().join("ReadRoot");
    let second = temp.path().join("OtherRoot");
    std::fs::create_dir(&first)?;
    std::fs::create_dir(&second)?;
    let canonical = dunce::canonicalize(&first)?;
    let alias = PathBuf::from(
        canonical
            .to_string_lossy()
            .replace('\\', "/")
            .to_ascii_uppercase(),
    );
    let first_sid = read_cap_sid_for_root(&first)?;
    let alias_sid = read_cap_sid_for_root(&alias)?;
    let second_sid = read_cap_sid_for_root(&second)?;
    LocalSid::from_string(&first_sid)?;
    LocalSid::from_string(&second_sid)?;
    assert_eq!(&first_sid, &alias_sid);
    assert_ne!(first_sid, second_sid);
    Ok(())
}
