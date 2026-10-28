use std::collections::BTreeSet;

use codex_hepta_agent_protocol::MAX_MEMORY_CELL_PAYLOAD_BYTES;
use codex_hepta_cognitive_store::MemoryCellWriteModeV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::CognitiveScope;
use serde_json::json;

use crate::AgentdPayload;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::record;
use crate::memory_cell_test_support::request;

#[tokio::test]
async fn cell_control_uses_real_owner_pagination_and_preserves_core_when_unconfigured() {
    let fixture = ControlFixture::new().await;
    assert!(
        fixture
            .client
            .memory_cell_snapshot(
                /*after*/ None, /*expected_owner_cut*/ None, /*limit*/ 2
            )
            .await
            .is_err()
    );
    fixture.ready();
    let owner = fixture.snapshot().await;
    let first = fixture
        .client
        .memory_cell_snapshot(
            /*after*/ None, /*expected_owner_cut*/ None, /*limit*/ 2,
        )
        .await
        .unwrap();
    assert_eq!(
        (
            first.records.len(),
            first.owner_cut_digest,
            first.scope.clone()
        ),
        (2, owner.owner_cut_digest(), owner.scope().clone())
    );
    let last = fixture
        .client
        .memory_cell_snapshot(
            first.next_after,
            Some(first.owner_cut_digest),
            /*limit*/ 2,
        )
        .await
        .unwrap();
    assert!(last.next_after.is_none());
    let rows: BTreeSet<_> = first
        .records
        .iter()
        .chain(&last.records)
        .map(|row| row.source_id)
        .collect();
    assert_eq!(rows, owner.current_source_ids().iter().copied().collect());
    assert!(
        fixture
            .client
            .memory_cell_read(request(owner.scope().clone()))
            .await
            .is_err()
    );
    assert!(
        fixture
            .client
            .memory_cell_snapshot(
                /*after*/ None, /*expected_owner_cut*/ None, /*limit*/ 3
            )
            .await
            .is_ok()
    );
    assert!(
        fixture
            .client
            .memory_cell_snapshot(
                first.next_after,
                /*expected_owner_cut*/ None,
                /*limit*/ 2
            )
            .await
            .is_err()
    );
    let invalid_cursor = ContractDigestV1::parse(&"1".repeat(64)).unwrap();
    assert!(
        fixture
            .client
            .memory_cell_snapshot(
                Some(invalid_cursor),
                Some(first.owner_cut_digest),
                /*limit*/ 2
            )
            .await
            .is_err()
    );
    fixture.finish().await;
}

#[tokio::test]
async fn cell_export_rejects_revision_drift_and_the_real_generation_fence() {
    let fixture = ControlFixture::new().await;
    fixture.ready();
    let first = fixture
        .client
        .memory_cell_snapshot(
            /*after*/ None, /*expected_owner_cut*/ None, /*limit*/ 1,
        )
        .await
        .unwrap();
    fixture
        .store
        .write_memory_cell(
            &fixture.access(),
            &CognitiveScope::AgentPrivate,
            &record(
                MemoryCellKindV1::Semantic,
                /*effective_at*/ 20,
                json!({"factor": 5, "label": "corrected"}),
            ),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
    assert!(
        fixture
            .client
            .memory_cell_snapshot(
                first.next_after,
                Some(first.owner_cut_digest),
                /*limit*/ 2
            )
            .await
            .is_err()
    );
    let fresh = fixture
        .client
        .memory_cell_snapshot(
            /*after*/ None, /*expected_owner_cut*/ None, /*limit*/ 3,
        )
        .await
        .unwrap();
    assert_ne!(fresh.owner_cut_digest, first.owner_cut_digest);
    assert!(
        fresh.records.iter().any(|row| row.revision == 2
            && row.record.value == json!({"factor": 5, "label": "corrected"}))
    );
    fixture
        .registry
        .compare_and_transition(
            &fixture.state.identity().agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .unwrap();
    assert!(
        fixture
            .client
            .memory_cell_snapshot(
                /*after*/ None, /*expected_owner_cut*/ None, /*limit*/ 3
            )
            .await
            .is_err()
    );
    fixture.finish().await;
}

#[tokio::test]
async fn cell_export_pages_by_encoded_bytes_and_never_returns_a_tombstoned_value() {
    let fixture = ControlFixture::new().await;
    fixture.ready();
    for index in 0..32 {
        let mut row = record(
            MemoryCellKindV1::Semantic,
            /*effective_at*/ 20,
            json!({"factor": index, "label": "\u{1}".repeat(256)}),
        );
        row.entity = ContractIdV1::new(format!("entity:escaped-{index}")).unwrap();
        fixture
            .store
            .write_memory_cell(
                &fixture.access(),
                &CognitiveScope::AgentPrivate,
                &row,
                MemoryCellWriteModeV1::Create,
            )
            .await
            .unwrap();
    }
    let first = fixture
        .client
        .memory_cell_snapshot(
            /*after*/ None, /*expected_owner_cut*/ None, /*limit*/ 32,
        )
        .await
        .unwrap();
    assert!(first.records.len() < 32 && first.next_after.is_some());
    assert!(
        serde_json::to_vec(&AgentdPayload::MemoryCellSnapshot(first))
            .unwrap()
            .len()
            <= MAX_MEMORY_CELL_PAYLOAD_BYTES
    );
    let withdrawn = record(
        MemoryCellKindV1::Semantic,
        /*effective_at*/ 20,
        json!({"factor": 3, "label": "owner semantic"}),
    );
    fixture
        .store
        .forget_memory_cell(
            &fixture.access(),
            &CognitiveScope::AgentPrivate,
            &withdrawn.address(),
            /*expected_revision*/ 1,
            "explicit test withdrawal",
            crate::memory_cell_runtime::now_unix_seconds().unwrap(),
        )
        .await
        .unwrap();
    let owner = fixture.snapshot().await;
    assert!(
        owner
            .current(&withdrawn.entity, MemoryCellKindV1::Semantic)
            .is_none()
    );
    let mut after = None;
    loop {
        let page = fixture
            .client
            .memory_cell_snapshot(after, Some(owner.owner_cut_digest()), /*limit*/ 32)
            .await
            .unwrap();
        assert!(
            !page
                .records
                .iter()
                .any(|row| row.record.entity == withdrawn.entity
                    && row.record.kind == withdrawn.kind)
        );
        after = page.next_after;
        if after.is_none() {
            break;
        }
    }
    fixture.finish().await;
}
