use super::*;

fn owner() -> OwnerContext {
    OwnerContext {
        required_mask: 8,
        optional_mask: 1,
        budget_total: 10_000,
        budget_remaining: 8_000,
        task_digest: [3; 32],
    }
}

#[test]
fn owner_contract_retains_identity_and_cannot_refill_budget() -> Result<()> {
    let previous = owner();
    let mut next = previous.clone();
    next.budget_remaining -= 1;
    next.validate_delivery_successor(&previous)?;
    let mut packet = Packet::default();
    next.write_packet(&mut packet);
    assert_eq!(OwnerContext::read_packet(&packet)?, next);
    next.budget_remaining = previous.budget_remaining + 1;
    assert!(next.validate_delivery_successor(&previous).is_err());
    for changed in [
        OwnerContext {
            required_mask: 9,
            ..previous.clone()
        },
        OwnerContext {
            task_digest: [4; 32],
            ..previous.clone()
        },
        OwnerContext {
            budget_total: 20_000,
            ..previous.clone()
        },
    ] {
        assert!(changed.validate_delivery_successor(&previous).is_err());
    }
    Ok(())
}

#[test]
fn prefix_features_track_progress_order_and_actual_bytes() -> Result<()> {
    let mut a = Prefixes {
        observed: true,
        ..Prefixes::default()
    };
    let mut b = a.clone();
    a.frame(/*modality*/ 3, /*units*/ 2, b"ab")?;
    b.frame(/*modality*/ 3, /*units*/ 2, b"ba")?;
    let oa = DeliveryObservation::new(&owner(), &a, [16, 1024, 4, 128])?;
    let ob = DeliveryObservation::new(&owner(), &b, [16, 1024, 4, 128])?;
    assert_ne!(oa.features(), ob.features());
    assert!(
        oa.features()
            .iter()
            .all(|value| value.is_finite() && (0.0..=1.0).contains(value))
    );
    assert!(!oa.required_complete());
    let empty = Prefixes {
        observed: true,
        ..Prefixes::default()
    };
    assert_ne!(
        DeliveryObservation::new(&owner(), &empty, oa.totals)?.features(),
        oa.features()
    );
    let forbidden = OwnerContext {
        required_mask: 1,
        optional_mask: 0,
        ..owner()
    };
    assert!(DeliveryObservation::new(&forbidden, &a, oa.totals).is_err());
    Ok(())
}
