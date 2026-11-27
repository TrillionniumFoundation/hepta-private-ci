//! Real private socket contracts, without authority or application qualification.
use super::*;
use serde_json::json;

#[test]
fn calculator_lost_effect_reply_disables_only_effect_and_keeps_correlated_readback() {
    let (effect, mut app_effect) = UnixStream::pair().unwrap();
    let (recovery, app_recovery) = UnixDatagram::pair().unwrap();
    let worker = std::thread::spawn(move || {
        let mut prefix = [0_u8; 4];
        app_effect.read_exact(&mut prefix).unwrap();
        let mut request = vec![0_u8; u32::from_be_bytes(prefix) as usize];
        app_effect.read_exact(&mut request).unwrap();
        assert_eq!(request, b"explicit effect fixture");
        drop(app_effect);
        let mut bytes = [0_u8; CALCULATOR_REQUEST_MAX_BYTES + 1];
        let length = app_recovery.recv(&mut bytes).unwrap();
        let request: serde_json::Value = serde_json::from_slice(&bytes[..length]).unwrap();
        assert_eq!(request["action"], "read_calculator");
        let mut response = json!({"schema_version":1,"action":"calculator_state","target":request["target"],"observation_id":"stale"});
        app_recovery
            .send(&serde_json::to_vec(&response).unwrap())
            .unwrap();
        response["observation_id"] = request["observation_id"].clone();
        app_recovery
            .send(&serde_json::to_vec(&response).unwrap())
            .unwrap();
    });
    let channel = AgentdCalculatorChannel::from_private_channels(effect, recovery).unwrap();
    let observer = channel.recovery_handle();
    assert!(channel.exchange(b"explicit effect fixture").is_err());
    assert!(channel.exchange(b"must not be sent again").is_err());
    drop(channel);
    let request = json!({"schema_version":1,"action":"read_calculator","target":{"fixture":true},"observation_id":"exact-fixture"});
    let response = observer
        .exchange(&serde_json::to_vec(&request).unwrap())
        .unwrap();
    let response: serde_json::Value = serde_json::from_slice(&response).unwrap();
    assert_eq!(response["observation_id"], "exact-fixture");
    worker.join().unwrap();
}

#[test]
fn calculator_recovery_rejects_effect_before_sending_any_datagram() {
    let (recovery, peer) = UnixDatagram::pair().unwrap();
    peer.set_nonblocking(true).unwrap();
    let channel = AgentdCalculatorRecoveryChannel::from_private_channel(recovery).unwrap();
    assert!(channel.exchange(br#"{"action":"evaluate"}"#).is_err());
    let mut bytes = [0_u8; 1];
    assert_eq!(
        peer.recv(&mut bytes).unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
}
