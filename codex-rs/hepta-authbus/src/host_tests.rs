use std::os::unix::fs::PermissionsExt;

use tempfile::TempDir;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityHost;

fn private_dir() -> TempDir {
    let directory = TempDir::new().expect("tempdir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private permissions");
    directory
}

#[tokio::test]
async fn second_owner_is_rejected_until_first_host_drops() {
    let database_root = private_dir();
    let checkpoint_root = private_dir();
    let database = database_root.path().join("authbus.sqlite");
    let checkpoint = checkpoint_root.path().join("checkpoint.json");
    let first = AuthBusAuthorityHost::open(&database, checkpoint.clone(), "owner-a")
        .await
        .expect("first owner");
    assert!(matches!(
        AuthBusAuthorityHost::open(&database, checkpoint.clone(), "owner-a").await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    drop(first);
    AuthBusAuthorityHost::open(&database, checkpoint, "owner-a")
        .await
        .expect("owner lock released after drop");
}
