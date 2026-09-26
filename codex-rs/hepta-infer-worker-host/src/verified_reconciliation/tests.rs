#[cfg(test)]
mod tests {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use tempfile::TempDir;

    use codex_hepta_infer_core::control_contract::OutputRetentionV1;
    use codex_hepta_infer_core::control_contract::RotatingTrustKeyV1;
    use codex_hepta_infer_core::control_contract::SettlementReceiptV1;
    use codex_hepta_infer_core::control_contract::SettlementVerifierV1;

    use super::*;

    fn digest(byte: u8) -> [u8; 32] {
        [byte; 32]
    }

    #[test]
    fn verified_receipt_is_persisted_before_digest_only_native_mapping() {
        let now = 1_800_000_000_000;
        let key = SigningKey::from_bytes(&[7; 32]);
        let receipt = SettlementReceiptV1 {
            schema_version: 1,
            receipt_id: "receipt-1".into(),
            request_id: "request-1".into(),
            admission_sha256: digest(1),
            manifest_sha256: digest(2),
            dispatch_sha256: digest(3),
            provider_id: "provider-1".into(),
            model_id: "model-1".into(),
            thread_id: "thread-1".into(),
            turn_id: "turn-1".into(),
            provider_sequence: 1,
            terminal: SettlementTerminalV1::Succeeded,
            output_sha256: Some(digest(4)),
            output_retention: OutputRetentionV1::DigestOnly,
            observed_input_tokens: Some(10),
            observed_output_tokens: Some(20),
            observed_cost_micros: Some(30),
            authority_epoch: 3,
            issued_at_unix_ms: now,
            expires_at_unix_ms: now + 60_000,
        };
        let signed = SignedSettlementReceiptV1 {
            signer_key_id: "settlement-a".into(),
            signature: key
                .sign(&receipt.signing_bytes().expect("signing bytes"))
                .to_bytes()
                .to_vec(),
            receipt,
        };
        let mut verifier = SettlementVerifierV1::new(vec![RotatingTrustKeyV1 {
            key_id: "settlement-a".into(),
            verifying_key: key.verifying_key().to_bytes(),
            not_before_authority_epoch: 1,
            not_after_authority_epoch: 9,
        }])
        .expect("trust");
        let verified = verifier
            .verify(
                &signed,
                "request-1",
                digest(1),
                digest(2),
                digest(3),
                now + 1,
            )
            .expect("verified");
        let temp = TempDir::new().expect("temp");
        let store = ReconciliationEvidenceStore::open(temp.path(), "native")
            .expect("store");
        let persisted = store
            .persist_settlement(&verified, &signed)
            .expect("persist");
        let output = native_output_from_verified_settlement(
            &verified,
            &persisted,
            NativeOwnerAuthority::ObservedReady,
        )
        .expect("mapping");
        assert!(output.output.is_empty());
        assert!(output.succeeded());
        assert_eq!(output.observed_output_tokens, Some(20));
        assert!(persisted.path().is_file());
    }
}
