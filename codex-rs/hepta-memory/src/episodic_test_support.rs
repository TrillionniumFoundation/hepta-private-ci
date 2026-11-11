use std::collections::BTreeMap;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use serde_json::Value;

use crate::CognitiveScope;
use crate::EpisodicRecordAdmission;
use crate::EpisodicSnapshotAdmission;
use crate::EpisodicSnapshotVerifier;
use crate::MemoryVerification;
use crate::cognitive_test_support::source;

pub(crate) type TestResult = Result<(), Box<dyn std::error::Error>>;

// Frozen complete-source fixtures; their canonical hashes were independently
// recomputed with Python json.dumps(sort_keys=True, ensure_ascii=False).
// UNICODE was emitted by the actual pinned EpisodicStore.export_snapshot.
pub(crate) const GOLDEN: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":1,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"route","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"9da1fafe5fde75bec5c885139496d8a5efd1c5f4dacfd6802304e546be30a8e7","source_uri":"fixture://route","source_version":"1"},"record_id":"d7a24d35085622e41780640b27e454d4e9b68f0af33321f79683a017c752843f","source_id":"source-a","text":"Use route blue.","version":1,"write_sequence":1}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"7de06091c154432340b6973938a53311b44ed7bbc3dc32b36e2a21d5ef2484a6"}"#;
pub(crate) const INCOMPLETE_DEPENDENCY: &str = r#"{"body":{"authority_id":"bridge-original-source-owner","generation":4,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"route","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"02bbd47c6798065603afb46f0bc505a5474b23371d372aca4a61c733fc97e47f","source_uri":"fixture://route","source_version":"2"},"record_id":"471981f50b02f9f8351c781eff23726c37452fb51a1dd51815ca41cbe70670de","source_id":"source-a","text":"Use route green.","version":2,"write_sequence":4},{"dependencies":["d7a24d35085622e41780640b27e454d4e9b68f0af33321f79683a017c752843f"],"key":"derived","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"2a4fbbdb68f1ad47b4a1a4e6e92e8a53ed259cefa076e2d30fe99aa975d01180","source_uri":"fixture://derived","source_version":"1"},"record_id":"cb489b504f4b7e981c8ef505d2927ae89071fe961709c30950acb727cb8afb51","source_id":"source-b","text":"The route evidence says blue.","version":1,"write_sequence":2},{"dependencies":[],"key":"unrelated","namespace":"bridge-fixture","provenance":{"episode_id":"source-episode","source_sha256":"1160510952698f0c61ba4864a9ab4fcbf7c2c4039971c602816a93d4faea8bfd","source_uri":"fixture://unrelated","source_version":"1"},"record_id":"329bae60950e23696c7caa7ef873d0625e5735ce4161bc5a52e4e9a7dad1d8c7","source_id":"source-c","text":"Use flow gamma.","version":1,"write_sequence":3}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"75da1bc33d94f16bc7383c8c8561be5522f21deb23a36e154b88c223d5a742c2"}"#;

pub(crate) const UNICODE: &str = r#"{"body":{"authority_id":"0000000000004000800000000000e001","generation":1,"namespace":"bridge-fixture","records":[{"dependencies":[],"key":"流程","namespace":"bridge-fixture","provenance":{"episode_id":"独立来源","source_sha256":"81b2ada28e09db7ffcc8f0f0dde36515818b1d79b29c75c4bbda85c7cc881e81","source_uri":"fixture://café/路径","source_version":"修订一"},"record_id":"df205a88266e26029285c4ae4e570edf47a2435888a26500de19e6af2820af4a","source_id":"源A","text":"更新：蓝色路径 café 🚀\n保留事实，而不是执行指令。","version":1,"write_sequence":1}],"schema":"hepta.mem6.snapshot.v1"},"sha256":"fb4e834f9e8d6cec04fcbbfa7c20b11f7f42aac1e9385754d336e2825581032e"}"#;

pub(crate) struct SourceWitness {
    pub(crate) expected: &'static str,
    pub(crate) admitted: EpisodicSnapshotAdmission,
    pub(crate) checks: AtomicUsize,
    pub(crate) reject_on_check: usize,
}

impl SourceWitness {
    pub(crate) fn current(expected: &'static str) -> Self {
        let value: Value = serde_json::from_str(expected).expect("fixture");
        let records = value["body"]["records"].as_array().expect("records").iter()
            .map(|record| {
                let id = record["record_id"].as_str().expect("id");
                (id.to_owned(), EpisodicRecordAdmission {
                    source: source(CognitiveScope::AgentPrivate, id, record["text"].as_str().expect("source fixture text")),
                    verification: MemoryVerification::Verified,
                })
            }).collect::<BTreeMap<_, _>>();
        Self {
            expected,
            admitted: EpisodicSnapshotAdmission { records, withdrawal: None },
            checks: AtomicUsize::new(0), reject_on_check: usize::MAX,
        }
    }

    pub(crate) fn authorize_withdrawal(&mut self) {
        self.admitted.withdrawal = Some(source(CognitiveScope::AgentPrivate,
            "source-owner-withdrawal", "Withdraw superseded source evidence."));
    }
}

impl EpisodicSnapshotVerifier for SourceWitness {
    fn verify_current(&self, snapshot_json: &str) -> Result<EpisodicSnapshotAdmission, String> {
        let check = self.checks.fetch_add(1, Ordering::SeqCst) + 1;
        if snapshot_json != self.expected || check == self.reject_on_check {
            return Err("original source owner no longer admits these bytes".to_owned());
        }
        Ok(self.admitted.clone())
    }
}

