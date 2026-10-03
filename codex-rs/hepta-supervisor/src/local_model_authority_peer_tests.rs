use super::RootFleetPeerAdmissionV1;
use std::path::Path;

#[tokio::test]
async fn ordinary_owner_cannot_open_a_root_peer_gate_or_read_its_policy() {
    if rustix::process::geteuid().as_raw() != 0 {
        let error = RootFleetPeerAdmissionV1::open(Path::new("/absent-private-peer-policy"))
            .await
            .err()
            .unwrap();
        assert_eq!(
            error.to_string(),
            "Fleet peer admission requires the actual Root owner"
        );
    }
}
