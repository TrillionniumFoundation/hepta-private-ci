//! Original registered fixture + real SQLite, with no Core listener. A known
//! pre-transport connection failure must leave first-dispatch eligibility intact.
use super::Fixture;
use anyhow::{Context,Result,ensure};
use crate::{AudioObservationBodyV1,SignedAudioObservationV1,audio_observation_claims};
use codex_hepta_codex_adapter::hmi::{HmiCapturedAudioRefV1,HmiCaptureStreamV1};
use codex_hepta_evidence::AuthBusDeliveryState;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

#[tokio::test]
async fn known_core_connection_failure_does_not_consume_audio_first_dispatch()->Result<()> {
    let mut fixture=Fixture::new().await;
    let home=&fixture.state.identity().home_root;
    let media=home.join("media");std::fs::create_dir(&media)?;std::fs::set_permissions(&media,std::fs::Permissions::from_mode(0o700))?;
    let file=media.join("capture-3-1.pcm16");std::fs::write(&file,[0,0,1,0])?;std::fs::set_permissions(&file,std::fs::Permissions::from_mode(0o600))?;
    let path=home.join("audio-authority.json");
    let policy=serde_json::json!({"schema_version":1,"agent_id":fixture.state.identity().agent_id.as_str(),"issuer_id":"issuer:test","key_epoch":1,
        "device_id":"device:unit-audio","device_generation":7,"organ_id":"organ:unit-audio","organ_generation":11,"capture_generation":3,
        "media_root":media,"max_segment_bytes":1048576,"expires_at_ms":crate::authbus_ingress::now_ms()?+300000,"revoked":false});
    let bytes=serde_json::to_vec(&policy)?;std::fs::write(&path,&bytes)?;std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o600))?;
    let state=Arc::get_mut(&mut fixture.state).context("exclusive existing fixture state")?;
    let host=Arc::get_mut(state.authbus.get_mut().context("existing AuthBus owner")?).context("exclusive existing ingress")?;
    host.audio_authority_file=Some(path);
    let source=HmiCapturedAudioRefV1 {stream:HmiCaptureStreamV1 {principal_id:"issuer:test".into(),device_id:"device:unit-audio".into(),device_generation:7,organ_id:"organ:unit-audio".into(),organ_generation:11,logical_session_id:"thread:thread:test".into()},
        capture_generation:3,sequence:1,asset_id:"capture-3-1.pcm16".into(),sha256:Digest32::of_bytes(&[0,0,1,0]).to_string(),byte_length:4,sample_rate:16000,num_channels:1,start_sample:10,end_sample:12};
    let mut request=SignedAudioObservationV1 {issuer_id:"issuer:test".into(),key_epoch:1,message_id:"audio:pre-transport".into(),sequence:1,expires_at_ms:crate::authbus_ingress::now_ms()?+300000,signature_hex:String::new(),
        body:AudioObservationBodyV1 {spawn_generation:1,thread_id:"thread:test".into(),text:"signed source waiting for its existing Core".into(),authority_sha256:Digest32::of_bytes(&bytes).to_string(),source}};
    request.signature_hex=fixture.key.sign(&audio_observation_claims(&fixture.state.identity().agent_id,&request)?.signing_bytes()).to_bytes().iter().map(|b|format!("{b:02x}")).collect();
    let receipt=crate::audio_observation::submit(&fixture.state,request).await?;
    ensure!(crate::audio_dispatch::tick(&fixture.state).await.is_err(),"the fixture deliberately has no Core listener");
    let host=crate::authbus_ingress::attached(&fixture.state)?;
    let state=host.evidence.authbus_delivery_status(receipt.delivery_id.parse()?).await?;
    ensure!(state.state==AuthBusDeliveryState::Queued && state.attempts==0,"known-not-sent audio lost first-dispatch eligibility: {state:?}");
    Ok(())
}
