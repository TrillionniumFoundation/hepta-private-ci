use super::*;
use pretty_assertions::assert_eq;

#[test]
fn acknowledgement_is_bound_to_actual_kernel_sender_and_complete_offer() {
    let sender = crate::worker_root_registration::process::observe(std::process::id()).unwrap();
    let (one, two) = UnixDatagram::pair().unwrap();
    enable_credentials(&two).unwrap();
    let digest = Sha256Digest::for_bytes(b"one sealed offer");
    let end = deadline(Duration::from_secs(1)).unwrap();
    send(&one, Phase::Acknowledged, &digest, end).unwrap();
    receive(&two, Phase::Acknowledged, &digest, &sender, end).unwrap();

    let mut wrong_sender = sender.clone();
    wrong_sender.pid = sender.pid.checked_add(1).unwrap();
    send(&one, Phase::Acknowledged, &digest, end).unwrap();
    assert_eq!(
        receive(&two, Phase::Acknowledged, &digest, &wrong_sender, end)
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );

    send(&one, Phase::Acknowledged, &digest, end).unwrap();
    assert!(receive(
        &two,
        Phase::Acknowledged,
        &Sha256Digest::for_bytes(b"different sealed offer"),
        &sender,
        end,
    )
    .is_err());
    send(&one, Phase::Acknowledged, &digest, end).unwrap();
    assert!(receive(&two, Phase::Confirmed, &digest, &sender, end).is_err());
}

#[test]
fn missing_credentials_or_lost_ack_never_confirms_registration() {
    let sender = crate::worker_root_registration::process::observe(std::process::id()).unwrap();
    let digest = Sha256Digest::for_bytes(b"unconfirmed sealed offer");
    let (one, two) = UnixDatagram::pair().unwrap();
    let end = deadline(Duration::from_secs(1)).unwrap();
    send(&one, Phase::Acknowledged, &digest, end).unwrap();
    assert!(receive(&two, Phase::Acknowledged, &digest, &sender, end).is_err());
    enable_credentials(&two).unwrap();
    assert!(receive(
        &two,
        Phase::Acknowledged,
        &digest,
        &sender,
        deadline(Duration::from_millis(10)).unwrap(),
    )
    .is_err());
}

#[test]
fn replay_from_previous_offer_and_extra_payload_are_refused() {
    let sender = crate::worker_root_registration::process::observe(std::process::id()).unwrap();
    let previous = Sha256Digest::for_bytes(b"old Root nonce and child lifetime");
    let current = Sha256Digest::for_bytes(b"new Root nonce and child lifetime");
    let (one, two) = UnixDatagram::pair().unwrap();
    enable_credentials(&two).unwrap();
    let end = deadline(Duration::from_secs(1)).unwrap();
    send(&one, Phase::Acknowledged, &previous, end).unwrap();
    assert!(receive(&two, Phase::Acknowledged, &current, &sender, end).is_err());
    let mut bytes = frame(Phase::Acknowledged, &current);
    bytes.push(0);
    one.send(&bytes).unwrap();
    assert!(receive(&two, Phase::Acknowledged, &current, &sender, end).is_err());
}
