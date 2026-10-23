//! Both signed profiles use the original outbox/Core delivery identity.
use crate::{AgentdError,AgentdState,AuthBusTextIngress};
use crate::hmi_text::authenticate;
use codex_hepta_codex_adapter::hmi::HmiBindingV1;
use serde_json::{Value,json};
use crate::SignedAudioObservationV1;

pub(super) enum SignedInput {
    Text(AuthBusTextIngress),
    Audio(Box<SignedAudioObservationV1>),
}
impl SignedInput {
    pub(super) fn authenticate(&self, state: &AgentdState) -> Result<String, AgentdError> {
        match self {
            Self::Text(request)=>authenticate(state,request),
            Self::Audio(request)=>crate::audio_observation::authenticate(state,request),
        }
    }
    pub(super) fn thread(&self) -> &str {
        match self { Self::Text(r)=>&r.body.thread_id, Self::Audio(r)=>&r.body.thread_id }
    }
    pub(super) fn text(&self) -> &str {
        match self { Self::Text(r)=>&r.body.text, Self::Audio(r)=>&r.body.text }
    }
    pub(super) fn sequence(&self) -> u64 {
        match self { Self::Text(r)=>r.sequence, Self::Audio(r)=>r.sequence }
    }
    pub(super) fn key_epoch(&self) -> u64 {
        match self { Self::Text(r)=>r.key_epoch, Self::Audio(r)=>r.key_epoch }
    }
    pub(super) fn audio_policy(&self) -> Option<String> {
        match self { Self::Text(_)=>None, Self::Audio(r)=>Some(r.body.authority_sha256.clone()) }
    }
    pub(super) fn set_binding(&self, state: &AgentdState, binding: &mut HmiBindingV1) {
        match self {
            Self::Text(r)=>{
                binding.principal_id=r.issuer_id.clone(); binding.device_id=format!("agent-ui:{}",state.identity().agent_id);
                binding.device_generation=r.key_epoch; binding.organ_id="hmi:text".into(); binding.organ_generation=state.identity().spawn_generation;
                binding.logical_session_id=format!("thread:{}",r.body.thread_id);
            }
            Self::Audio(r)=>{
                let s=&r.body.source.stream;
                binding.principal_id=s.principal_id.clone(); binding.device_id=s.device_id.clone(); binding.device_generation=s.device_generation;
                binding.organ_id=s.organ_id.clone(); binding.organ_generation=s.organ_generation; binding.logical_session_id=s.logical_session_id.clone();
            }
        }
    }
    pub(super) fn matches(&self, state: &AgentdState, binding: &HmiBindingV1) -> bool {
        let mut expected=binding.clone(); self.set_binding(state,&mut expected);
        self.thread()==binding.thread_id && expected==*binding
    }
    pub(super) fn context(&self, delivery: &str) -> Value {
        match self {
            Self::Text(r)=>json!({"deliveryId":delivery,"messageId":r.message_id,"threadId":r.body.thread_id,"text":r.body.text}),
            Self::Audio(r)=>json!({"deliveryId":delivery,"messageId":r.message_id,"threadId":r.body.thread_id,"text":r.body.text,"source":r.body.source,"authoritySha256":r.body.authority_sha256}),
        }
    }
    pub(super) async fn admit(self, state: &AgentdState) -> Result<Value, AgentdError> {
        match self {
            Self::Text(r)=>Ok(serde_json::to_value(crate::authbus_ingress::submit(state,r).await?)?),
            Self::Audio(r)=>{
                let receipt=crate::audio_observation::submit(state,*r).await?;
                // Keep the canonical receipt as its own typed audio observation.
                // The outer admission ID is shared by the owner loop only.
                Ok(json!({"delivery_id":receipt.delivery_id,"audioObservation":receipt}))
            }
        }
    }
}
