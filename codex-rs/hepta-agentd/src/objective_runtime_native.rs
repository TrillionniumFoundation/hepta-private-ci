// Finite canonical data/claims helpers used by the original Root issuer.
// No objective runtime, journal, replay admission or effect owner is created.
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;

include!("objective_claims.rs");
