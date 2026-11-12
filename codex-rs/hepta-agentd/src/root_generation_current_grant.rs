//! One request on the actual sealed CURRENT lane. This is not a generic issuer.

use codex_hepta_contracts::SignedFinalUseGrant;

use super::*;
use crate::neuron_generation_current::types::UpdateIntent;

impl RootGenerationCurrentClient {
    pub(crate) fn issue_original_prepared_final_use(
        &self,
        intent: &UpdateIntent,
    ) -> Result<SignedFinalUseGrant, AgentdError> {
        let result = (|| {
            if self.grant_attempted.swap(true, Ordering::AcqRel)
                || self.version != PublicationVersion::DurableV2
                || intent != &self.profile.intent
            {
                return Err(uncertain());
            }
            let before = self.observe()?;
            if before.current != intent.previous || before.prepared.as_ref() != Some(intent) {
                return Err(uncertain());
            }
            let response = self.exchange_response(Command::IssueFinalUse {
                expected: head_digest(&before)?,
                intent: intent.digest()?.to_string(),
            })?;
            if response.head != before || response.successor.is_some() {
                return Err(uncertain());
            }
            let signed = response.grant.ok_or_else(uncertain)?;
            if signed.grant.binding != intent.binding()? {
                return Err(uncertain());
            }
            signed.grant.signing_bytes().map_err(|_| uncertain())?;
            self.connection.require_original_publication_session()?;
            Ok(signed)
        })();
        if result.is_err() {
            self.fence();
        }
        result
    }
}
