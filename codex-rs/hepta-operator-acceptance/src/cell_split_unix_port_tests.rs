use super::*;
use std::os::unix::net::UnixListener;
use std::thread;

use crate::CellSplitExecutionStepV1;

fn private_root() -> tempfile::TempDir {
    let dir = tempfile::tempdir().expect("socket root");
    use std::os::unix::fs::PermissionsExt as _;
    fs::set_permissions(dir.path(), fs::Permissions::from_mode(0o700)).expect("private root");
    dir
}

fn bound_sockets(
    root: &Path,
) -> (
    [CellSplitUnixEndpointV1; OWNER_COUNT],
    Vec<UnixListener>,
) {
    let endpoints = [0, 1, 2, 3].map(|index| CellSplitUnixEndpointV1 {
        owner_id: format!("external-owner-{index}"),
        socket_path: root.join(format!("effect-{index}.sock")),
    });
    let listeners = endpoints
        .iter()
        .map(|endpoint| UnixListener::bind(&endpoint.socket_path).expect("bind socket"))
        .collect();
    (endpoints, listeners)
}

fn intent() -> CellSplitExecutionIntentV1 {
    CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest: "11".repeat(32),
        step: CellSplitExecutionStepV1::ArtifactCas,
        owner_id: "external-owner-0".into(),
        idempotency_key: "22".repeat(32),
        previous_receipt_digest: "33".repeat(32),
    }
}

fn receipt(intent: &CellSplitExecutionIntentV1) -> CellSplitExecutionReceiptV1 {
    CellSplitExecutionReceiptV1 {
        intent: intent.clone(),
        owner_sequence: 77,
        output_digest: "44".repeat(32),
        owner_receipt_bytes: b"actual owner-signed receipt".to_vec(),
        owner_signature_bytes: vec![9; 64],
        receipt_digest: "55".repeat(32),
    }
}

fn exchange(
    listener: &UnixListener,
    expected: RpcOperationV1,
    response_owner: &str,
    committed: Option<CellSplitExecutionReceiptV1>,
) {
    let (mut stream, _) = listener.accept().expect("owner accepts one RPC");
    let mut header = [0u8; 4];
    stream.read_exact(&mut header).expect("read request header");
    let size = u32::from_be_bytes(header) as usize;
    assert!(size > 0 && size <= RPC_LIMIT);
    let mut body = vec![0; size];
    stream.read_exact(&mut body).expect("read request");
    let request: RpcRequestV1 = serde_json::from_slice(&body).expect("decode request");
    assert_eq!(request.schema, RPC_SCHEMA);
    assert_eq!(request.operation, expected);
    assert_eq!(body, canonical_json(&request).expect("canonical"));
    let response = RpcResponseV1 {
        schema: RPC_SCHEMA.into(),
        operation: expected,
        intent: request.intent,
        owner_id: response_owner.into(),
        receipt: committed,
        failure: None,
    };
    let body = canonical_json(&response).expect("reply JSON");
    stream
        .write_all(&(body.len() as u32).to_be_bytes())
        .expect("write reply length");
    stream.write_all(&body).expect("write reply");
}

#[test]
fn unix_port_executes_once_then_verifies_with_fresh_read_only_rpc() {
    let root = private_root();
    let (endpoints, mut listeners) = bound_sockets(root.path());
    let mut port = CellSplitUnixPortV1::new(root.path(), endpoints).expect("admitted sockets");
    let listener = listeners.remove(0);
    let request = intent();
    let proof = receipt(&request);
    let proof_for_owner = proof.clone();
    let server = thread::spawn(move || {
        exchange(
            &listener,
            RpcOperationV1::Execute,
            "external-owner-0",
            Some(proof_for_owner.clone()),
        );
        exchange(
            &listener,
            RpcOperationV1::ReadCommitted,
            "external-owner-0",
            Some(proof_for_owner.clone()),
        );
        exchange(
            &listener,
            RpcOperationV1::ReadCommitted,
            "external-owner-0",
            Some(proof_for_owner),
        );
    });
    assert_eq!(port.execute(&request).expect("real owner reply"), proof);
    port.verify_committed(&request, &proof)
        .expect("must read external owner again");
    assert_eq!(port.reconcile(&request).expect("read"), Some(proof));
    server.join().expect("socket server");
}

#[test]
fn unix_port_rejects_owner_substitution_and_missing_committed_effect() {
    let root = private_root();
    let (endpoints, mut listeners) = bound_sockets(root.path());
    let mut port = CellSplitUnixPortV1::new(root.path(), endpoints).expect("admitted sockets");
    let listener = listeners.remove(0);
    let request = intent();
    let proof = receipt(&request);
    let server = thread::spawn(move || {
        exchange(&listener, RpcOperationV1::Execute, "impostor", Some(proof));
        exchange(
            &listener,
            RpcOperationV1::ReadCommitted,
            "external-owner-0",
            None,
        );
    });
    assert!(matches!(
        port.execute(&request),
        Err(CellSplitUnixPortErrorV1::Invalid(_))
    ));
    assert!(matches!(
        port.verify_committed(&request, &receipt(&request)),
        Err(CellSplitUnixPortErrorV1::Invalid(_))
    ));
    server.join().expect("socket server");
}

#[test]
fn unix_port_fails_closed_for_socket_alias_or_wrong_intent_owner() {
    let root = private_root();
    let (mut endpoints, listeners) = bound_sockets(root.path());
    let mut wrong_owner = intent();
    wrong_owner.owner_id = "external-owner-3".into();
    let mut port =
        CellSplitUnixPortV1::new(root.path(), endpoints.clone()).expect("admitted sockets");
    assert!(matches!(
        port.reconcile(&wrong_owner),
        Err(CellSplitUnixPortErrorV1::Invalid(_))
    ));

    endpoints[1].socket_path = endpoints[0].socket_path.clone();
    assert!(CellSplitUnixPortV1::new(root.path(), endpoints.clone()).is_err());
    endpoints[1].socket_path = root.path().join("effect-1.sock");
    let alias = root.path().join("alias.sock");
    std::os::unix::fs::symlink(&endpoints[0].socket_path, &alias).expect("create alias");
    endpoints[1].socket_path = alias;
    assert!(CellSplitUnixPortV1::new(root.path(), endpoints).is_err());
    drop(listeners);
}
