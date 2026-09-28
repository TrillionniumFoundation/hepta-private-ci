//! Prevent derived Debug (including nested error Debug) from exporting secret
//! fingerprints. Wire serialization stays unchanged and remains owner-only.
use std::fmt;
use crate::{BaoConsumptionOperationV1, BaoReadRequest, BaoSecretReceipt, OpaqueSecretReceipt, SecretLease, SecretReference, SecretRequest};

impl fmt::Debug for BaoSecretReceipt {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("BaoSecretReceipt([SENSITIVE METADATA REDACTED])")
    }
}
impl fmt::Debug for BaoReadRequest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("BaoReadRequest([SENSITIVE BINDING REDACTED])")
    }
}
impl fmt::Debug for BaoConsumptionOperationV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BaoConsumptionOperationV1").field("state", &self.state)
            .field("recovery_action", &self.recovery_action()).finish_non_exhaustive()
    }
}
impl fmt::Debug for SecretReference {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str("SecretReference([REDACTED])") }
}
impl fmt::Debug for SecretLease {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str("SecretLease([REDACTED])") }
}
impl fmt::Debug for SecretRequest {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str("SecretRequest([REDACTED])") }
}
impl fmt::Debug for OpaqueSecretReceipt {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { f.write_str("OpaqueSecretReceipt([REDACTED])") }
}
