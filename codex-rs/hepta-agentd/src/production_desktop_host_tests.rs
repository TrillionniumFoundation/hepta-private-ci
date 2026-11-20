//! Original writer/FinalUse and actual private descriptor tests. The issuer and
//! X-server result below are explicit fixtures, not production/root evidence.
use super::*;
use codex_hepta_memory::DESKTOP_INPUT_TOPIC_V1;
use codex_hepta_memory::DesktopBootstrapOffer;
use codex_hepta_memory::desktop_operation_intent;
use pretty_assertions::assert_eq;

fn golden() -> serde_json::Value {
    serde_json::from_str(include_str!("../tests/fixtures/desktop-x11-v1.json")).unwrap()
}
fn field(name: &str) -> String {
    golden()[name].as_str().unwrap().to_string()
}

fn send_offer(
    bootstrap: &UnixDatagram,
    offer: &[u8],
    effect: &UnixStream,
    observe: &UnixStream,
) -> std::io::Result<()> {
    let mut vector = libc::iovec {
        iov_base: offer.as_ptr().cast_mut().cast(),
        iov_len: offer.len(),
    };
    let mut control = [0usize; 4];
    // SAFETY: borrowed descriptors and bounded buffers remain live through sendmsg.
    let sent = unsafe {
        let mut message: libc::msghdr = mem::zeroed();
        message.msg_iov = &mut vector;
        message.msg_iovlen = 1;
        message.msg_control = control.as_mut_ptr().cast();
        message.msg_controllen =
            libc::CMSG_SPACE((2 * mem::size_of::<libc::c_int>()) as u32) as usize;
        let header = libc::CMSG_FIRSTHDR(&message);
        (*header).cmsg_level = libc::SOL_SOCKET;
        (*header).cmsg_type = libc::SCM_RIGHTS;
        (*header).cmsg_len = libc::CMSG_LEN((2 * mem::size_of::<libc::c_int>()) as u32) as usize;
        libc::CMSG_DATA(header)
            .cast::<libc::c_int>()
            .write(effect.as_raw_fd());
        libc::CMSG_DATA(header)
            .cast::<libc::c_int>()
            .add(1)
            .write(observe.as_raw_fd());
        libc::sendmsg(bootstrap.as_raw_fd(), &message, libc::MSG_NOSIGNAL)
    };
    if sent == offer.len() as isize {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}
fn read_frame(stream: &mut UnixStream) -> std::io::Result<Vec<u8>> {
    stream.set_read_timeout(Some(Duration::from_secs(15)))?;
    let mut size = [0; 4];
    stream.read_exact(&mut size)?;
    let size = u32::from_be_bytes(size) as usize;
    if size == 0 || size > 8192 {
        return Err(std::io::ErrorKind::InvalidData.into());
    }
    let mut bytes = vec![0; size];
    stream.read_exact(&mut bytes)?;
    Ok(bytes)
}
fn send_frame(stream: &mut UnixStream, bytes: &[u8]) -> std::io::Result<()> {
    stream.set_write_timeout(Some(Duration::from_secs(2)))?;
    stream.write_all(&(bytes.len() as u32).to_be_bytes())?;
    stream.write_all(bytes)
}

#[tokio::test]
async fn desktop_original_owner_lost_reply_observes_exact_terminal_without_retry()
-> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory: _directory,
        config,
        host,
        issuer,
        final_use,
        ..
    } = notes_host_fixture().await?;
    let (owner_bootstrap, peer_bootstrap) = UnixDatagram::pair()?;
    let (effect, mut peer_effect) = UnixStream::pair()?;
    let (observe, mut peer_observe) = UnixStream::pair()?;
    let peer = std::thread::spawn(move || -> Result<(), String> {
        send_offer(
            &peer_bootstrap,
            field("offer_raw").as_bytes(),
            &effect,
            &observe,
        )
        .map_err(|e| e.to_string())?;
        drop(effect);
        drop(observe);
        peer_bootstrap
            .set_read_timeout(Some(Duration::from_secs(4)))
            .map_err(|e| e.to_string())?;
        let mut ack = [0; 1024];
        let got = peer_bootstrap.recv(&mut ack).map_err(|e| e.to_string())?;
        assert_eq!(&ack[..got], field("ack_raw").as_bytes());
        assert_eq!(
            read_frame(&mut peer_effect).map_err(|e| e.to_string())?,
            field("input_raw").as_bytes()
        );
        peer_effect
            .shutdown(std::net::Shutdown::Both)
            .map_err(|e| e.to_string())?;
        let mut unknown: serde_json::Value = serde_json::from_str(&field("receipt_raw")).unwrap();
        unknown["result"] = serde_json::json!({"status":"unknown","current_sequence":0});
        for reply in [
            serde_json::to_vec(&unknown).unwrap(),
            field("receipt_raw").into_bytes(),
        ] {
            let query: serde_json::Value =
                serde_json::from_slice(&read_frame(&mut peer_observe).map_err(|e| e.to_string())?)
                    .unwrap();
            assert_eq!(
                query,
                serde_json::from_str::<serde_json::Value>(&field("observe_raw")).unwrap()
            );
            send_frame(&mut peer_observe, &reply).map_err(|e| e.to_string())?;
        }
        Ok(())
    });
    let (target, offer) = crate::receive_desktop_session(owner_bootstrap)?;
    let host = host.attach_target(final_use, Arc::new(target), issuer.clone())?;
    let payload = field("input_raw");
    let intent = desktop_operation_intent(
        &offer.target,
        &payload,
        StableId::new(config.identity().agent_id.as_str())?,
        Generation::new(1)?,
    )?;
    let queued = host
        .writer()
        .prepare_operation(intent, DESKTOP_INPUT_TOPIC_V1, payload)
        .await?;
    let receipt = host.dispatch_with_grant_provider(queued.clone()).await?;
    assert_eq!(receipt.state, LocalOutcomeState::Indeterminate);
    assert!(
        host.writer()
            .apply(&queued.occurrence_key, "invented success")
            .await
            .is_err()
    );
    assert!(
        host.writer()
            .reconcile(
                &queued.occurrence_key,
                codex_hepta_memory::LocalReconcileOutcome::Committed
            )
            .await
            .is_err()
    );
    assert_eq!(host.reconcile(1).await?, 1);
    assert_eq!(
        host.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(host.reauthorize_pending(1).await?, 0);
    assert_eq!(host.reconcile(1).await?, 1);
    assert_eq!(
        host.writer().status(&queued.occurrence_key).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(issuer.requests.load(Ordering::SeqCst), 1);
    assert_eq!(
        offer,
        DesktopBootstrapOffer::parse_exact(field("offer_raw").as_bytes())?
    );
    peer.join().expect("fixture peer")?;
    host.close().await?;
    Ok(())
}

#[path = "production_desktop_gui_tests.rs"]
mod gui_tests;
