//! Real original sockets/pidfds; synthetic synchronous application refusals.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn original_response_refusal_after_prefix_never_writes_body_or_retries() {
    let (mut server, mut client) = channel(32);
    send(&mut client, b"request");
    let mut checks = 0;
    assert_eq!(
        server.exchange_with_original_response(|_, response| {
            response.write_response(b"private", || {
                checks += 1;
                if checks == 1 {
                    Ok(())
                } else {
                    Err(HostIssuerTransportError::PeerDenied)
                }
            })
        }),
        Err(HostIssuerTransportError::PeerDenied)
    );
    let mut received = Vec::new();
    client.read_to_end(&mut received).unwrap();
    assert_eq!(received, (7_u32).to_be_bytes());
    assert_eq!(checks, 2);
    assert_eq!(
        server.exchange(|_| unreachable!()),
        Err(HostIssuerTransportError::Closed)
    );
}

#[test]
fn original_response_missing_or_reused_writer_cannot_report_success() {
    let (mut server, mut client) = channel(32);
    send(&mut client, b"request");
    assert_eq!(
        server.exchange_with_original_response(|_, _| Ok(())),
        Err(HostIssuerTransportError::Unavailable)
    );
    let mut received = Vec::new();
    client.read_to_end(&mut received).unwrap();
    assert!(received.is_empty());
    let (mut server, mut client) = channel(32);
    send(&mut client, b"request");
    assert_eq!(
        server.exchange_with_original_response(|_, response| {
            response.write_response(b"first", || Ok(()))?;
            assert_eq!(
                response.write_response(b"second", || Ok(())),
                Err(HostIssuerTransportError::Closed)
            );
            Ok(())
        }),
        Err(HostIssuerTransportError::Unavailable)
    );
    let mut received = Vec::new();
    client.read_to_end(&mut received).unwrap();
    assert_eq!(
        received,
        [5_u32.to_be_bytes().as_slice(), b"first"].concat()
    );
}

#[test]
fn original_response_private_fence_cannot_extend_the_frame_deadline() {
    let (mut server, mut client) = channel(32);
    send(&mut client, b"request");
    assert_eq!(
        server.exchange_with_original_response(|_, response| {
            response.write_response(b"late", || {
                std::thread::sleep(Duration::from_millis(150));
                Ok(())
            })
        }),
        Err(HostIssuerTransportError::DeadlineElapsed)
    );
    let mut received = Vec::new();
    client.read_to_end(&mut received).unwrap();
    assert!(received.is_empty());
}

#[test]
fn original_response_current_peer_rejects_eof_and_pipelined_data() {
    for additional in [None, Some(b"unexpected".as_slice())] {
        let (mut server, mut client) = channel(32);
        send(&mut client, b"request");
        if let Some(additional) = additional {
            client.write_all(additional).unwrap();
        } else {
            client.shutdown(std::net::Shutdown::Write).unwrap();
        }
        assert_eq!(
            server.exchange_with_original_response(|_, response| {
                response.write_response(b"private", || {
                    response.current().recheck_original_exchange()
                })
            }),
            Err(HostIssuerTransportError::PeerDenied)
        );
        let mut received = Vec::new();
        client.read_to_end(&mut received).unwrap();
        assert!(received.is_empty());
    }
}
