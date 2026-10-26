use codex_hepta_automation::AsyncAuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectFuture;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedProviderEffectRequest;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::Sha256Digest;

use super::RuntimeProcessObservation;
use super::RuntimeProcessOwner;

pub(super) struct RuntimeProcessDriver<A> {
    pub owner: A,
    pub intent: ProviderEffectIntent,
}

impl<A: RuntimeProcessOwner> AsyncAuthorizedEffectDriver for RuntimeProcessDriver<A> {
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            if request.provider_intent != self.intent
                || Sha256Digest::for_bytes(request.wire_payload) != self.intent.payload_sha256
            {
                return Err(AuthorizedEffectDriverError::BeforeProviderContact);
            }
            if let RuntimeProcessObservation::Terminal(result) = self
                .owner
                .dispatch(&self.intent, request.wire_payload)
                .await
                && let Ok(receipt) = result.receipt(&self.intent)
            {
                return Ok(receipt);
            }
            // An invalid/lost result after possible contact is never absence.
            let bytes = format!(
                "hepta.native-agent.runtime-process-unresolved.v1\0{}\0{}",
                self.intent.key.as_str(),
                self.intent.payload_sha256.as_str()
            );
            Ok(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Indeterminate,
                receipt_digest: Sha256Digest::for_bytes(bytes.as_bytes()),
            })
        })
    }
}
