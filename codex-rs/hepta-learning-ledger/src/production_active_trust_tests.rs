use super::*;
use pretty_assertions::assert_eq;

fn writer_bytes(writer: &LedgerWriter) -> (Vec<u8>, Vec<u8>) {
    let LedgerBackend::Durable(ledger) = &writer.backend else {
        panic!("original durable fixture backend");
    };
    (
        ledger.held_fixture_bytes(),
        writer.witness.held_fixture_bytes(),
    )
}

#[test]
fn signed_decision_requires_current_distribution_without_writes_after_expiry()
-> Result<(), Box<dyn std::error::Error>> {
    for now in [49, 50, 51] {
        let fixture = Fixture::new();
        let mut writer = fixture.writer_with_trust(activated_trust_until(
            /*expires_at*/ 50, /*now*/ 49,
        ));
        let request = decision();
        let payload = decision_signing_payload_v2(&request)?;
        let evidence = sign(
            writer.verifier(),
            "generator",
            LearningEvidenceRoleV1::Generator,
            &payload,
        );
        // The role credential and signature remain valid after the root-signed
        // distribution expires, so signature admission alone is insufficient.
        writer
            .verifier()
            .verify(LearningEvidenceRoleV1::Generator, &evidence, &payload, now)?;
        let before = writer_bytes(&writer);
        let frontier = writer.witness_frontier()?;
        let result = writer.append_decision(Digest32::ZERO, request, &evidence, now);
        if now == 49 {
            assert_eq!(result?.disposition, AppendDisposition::Appended);
            assert_eq!(writer.records()?.len(), 1);
            assert_eq!(writer.witness_frontier()?.anchor.sequence, 1);
        } else {
            assert!(matches!(
                result,
                Err(ProductionLedgerError::Binding(
                    "learning trust is not current"
                ))
            ));
            assert!(writer.records()?.is_empty());
            assert_eq!(writer.witness_frontier()?, frontier);
            assert_eq!(writer_bytes(&writer), before);
        }
    }
    Ok(())
}
