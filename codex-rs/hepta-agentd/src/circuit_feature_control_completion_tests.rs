//! Actual signed ObjectiveStart after a transport timeout and client drop.
//! Original role keys/CURRENT deployment are component fixtures.

use codex_uds::UnixStream;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use tokio::io::AsyncWriteExt;

use super::*;

#[tokio::test]
async fn feature_socket_ack_timeout_recovers_original_completion_without_redispatch()
-> anyhow::Result<()> {
    let f = FeatureFixture::with_control(
        /*deadline_offset*/ 300,
        ControlFixture::DelayedOriginal,
    )
    .await?;
    assert!(f.ingress.readback().is_err());
    let began = std::time::Instant::now();
    // The real typed driver receives the unchanged client's 2s ACK timeout.
    // Its only recovery is the retained source/Cell, not another submission.
    let source = f.ingress.submit(f.session.request.clone()).await?;
    assert!(began.elapsed() >= Duration::from_secs(2));
    let _next_dataset = source.original_dataset_task()?;
    let committed = owner_bytes(&f.session)?;
    let _same_original_source = f.ingress.readback()?;
    assert_eq!(owner_bytes(&f.session)?, committed);

    // A newly signed request with the same run/Cell may not borrow the older
    // publication when its own transport response is lost.
    let mut alias = f.session.request.clone();
    alias.message_id.push_str("-alias");
    alias.sequence += 1;
    alias.signature_hex = SigningKey::from_bytes(&[91; 32])
        .sign(
            &crate::authbus_objective_claims(&f.session.runtime.identity, &alias)?.signing_bytes(),
        )
        .to_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let error = match f.ingress.submit(alias).await {
        Ok(_) => anyhow::bail!("a different signed request reused original completion"),
        Err(error) => error,
    };
    assert!(
        error
            .to_string()
            .contains("original Feature authentication differs")
    );
    assert_eq!(owner_bytes(&f.session)?, committed);
    f.finish().await
}

#[tokio::test]
async fn feature_socket_client_drop_keeps_original_source_and_cell_once() -> anyhow::Result<()> {
    let f = FeatureFixture::with_control(
        /*deadline_offset*/ 300,
        ControlFixture::DelayedOriginal,
    )
    .await?;
    let mut stream = UnixStream::connect(&f.session.runtime.identity.control_socket).await?;
    let request = crate::AgentdRequest::objective_start(
        /*request_id*/ 1,
        f.session.runtime.identity.spawn_generation,
        f.session.request.clone(),
    );
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    stream.write_all(&bytes).await?;
    drop(stream); // The caller disappears after one complete signed frame.
    let source = f.observe_original_completion().await?;
    let _next_dataset = source.original_dataset_task()?;
    let publication = f.session.source.read_run_publication(
        &f.session.runtime.identity,
        &StableId::new(&f.session.request.body.run_id)?,
    )?;
    let _original_decision = f.session.cell.committed(&publication)?;
    let committed = owner_bytes(&f.session)?;
    for _ in 0..3 {
        let _same_original_source = f.ingress.readback()?;
        assert_eq!(
            f.session.source.read_run_publication(
                &f.session.runtime.identity,
                &StableId::new(&f.session.request.body.run_id)?,
            )?,
            publication,
        );
        assert_eq!(owner_bytes(&f.session)?, committed);
    }
    f.finish().await
}
