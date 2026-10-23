//! Original HOS2 owner plus explicit native-history and protected-peer fixtures.
//! No native install is dispatched; this is not guest/kernel qualification.

use super::*;
use crate::Hos2DeliveryId;
use crate::Hos2DeliveryObservation;
use crate::Hos2Device;
use crate::Hos2InstallBudgetV1;
use crate::Hos2InstallOutcome;
use crate::Hos2RetirementObservation;
use crate::Hos2RetirementPermit;
use crate::ProductionHos2Target;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;

struct HistoryDevice {
    request: Hos2InstallBudgetV1,
    retirements: AtomicUsize,
}
impl Hos2Device for HistoryDevice {
    fn install(&self, _request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String> {
        panic!("history retirement must never install")
    }
    fn observe(&self, request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String> {
        assert_eq!(request, &self.request);
        self.query(&request.delivery)
            .map(Hos2InstallOutcome::Observed)
    }
    fn query(&self, delivery: &Hos2DeliveryId) -> Result<Hos2DeliveryObservation, String> {
        assert_eq!(delivery, &self.request.delivery);
        Ok(Hos2DeliveryObservation::Applied {
            stable_object_id: [9; 16],
            previous_revision: 1,
            revision: 2,
            effective_ns: crate::HOS2_CPU_PERIOD_NS + 1_001,
            consumed_ns: 999,
        })
    }
    fn retire(&self, permit: &Hos2RetirementPermit) -> Result<Hos2RetirementObservation, String> {
        assert_eq!(permit.through(), &self.request.delivery);
        self.retirements.fetch_add(1, Ordering::SeqCst);
        Ok(Hos2RetirementObservation {
            retired_through: 1,
            next_sequence: 2,
        })
    }
}

async fn settled_hos2(fixture: &ManagedFixture) -> (Arc<HistoryDevice>, Arc<ProductionHos2Target>) {
    let request = Hos2InstallBudgetV1 {
        schema_version: 1,
        delivery: Hos2DeliveryId::new([1; 16], [2; 16], 1).unwrap(),
        manage_slot: 2,
        manage_generation: 1,
        expected_revision: 1,
        period_ns: crate::HOS2_CPU_PERIOD_NS,
        cap_ns: 1_001,
    };
    let payload = request.to_json().unwrap();
    let intent = OperationIntentV1::new(
        StableId::new("hos2:protected:retirement").unwrap(),
        StableId::new(fixture.writer.owner_agent_id().as_str()).unwrap(),
        StableId::new(crate::HOS2_DESTINATION_V1).unwrap(),
        Digest32::of_bytes(payload.as_bytes()),
        request.scope_digest(),
        Generation::new(1).unwrap(),
        /*expected_predecessor*/ None,
    )
    .unwrap();
    let queued = fixture
        .writer
        .prepare_operation(intent, crate::HOS2_INSTALL_TOPIC_V1, payload)
        .await
        .unwrap();
    fixture
        .writer
        .mark_indeterminate(&queued.occurrence_key, "fixture original install ACK lost")
        .await
        .unwrap();
    let device = Arc::new(HistoryDevice {
        request,
        retirements: AtomicUsize::new(0),
    });
    let target = Arc::new(ProductionHos2Target::new(device.clone()));
    assert_eq!(
        fixture
            .writer
            .reconcile_target_batch(target.as_ref(), /*limit*/ 1)
            .await
            .unwrap(),
        1
    );
    (device, target)
}

#[tokio::test]
async fn hos2_retirement_requires_bound_whole_owner_ack_before_discarding_native_history() {
    let fixture = ManagedFixture::new().await;
    let (device, target) = settled_hos2(&fixture).await;
    fixture
        .peer
        .hold_current_reply
        .store(true, Ordering::SeqCst);
    let result = fixture
        .writer
        .retire_hos2_through(&target, &device.request.delivery)
        .await;
    assert_eq!(
        device.retirements.load(Ordering::SeqCst),
        0,
        "native history cannot retire from a merely local terminal prefix while independent Current is unacknowledged"
    );
    assert!(result.is_err());
    assert!(fixture.store.commit_gate.is_fenced());
}
