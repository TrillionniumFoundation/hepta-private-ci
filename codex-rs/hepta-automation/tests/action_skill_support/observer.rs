//! Independent goal observation and content-addressed evidence retention.

use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_automation::ActionCancellationStateV1;
use codex_hepta_automation::ActionConditionV1;
use codex_hepta_automation::ActionExecutionStateV1;
use codex_hepta_automation::ActionGoalStateV1;
use codex_hepta_automation::ActionInitiationObservationV1;
use codex_hepta_automation::ActionSkillBindingV1;
use codex_hepta_automation::ActionSkillBudgetV1;
use codex_hepta_automation::ActionSkillContractV1;
use codex_hepta_automation::ActionSkillError;
use codex_hepta_automation::ActionSkillObservationV1;
use codex_hepta_automation::ActionSkillObserver;
use codex_hepta_automation::ActionSkillRecoveryV1;
use codex_hepta_automation::GoalCheckedActionSkillDriver;
use codex_hepta_contracts::Sha256Digest;
use sqlx::SqlitePool;

use super::destination::Desired;
use super::destination::Destination;
use super::destination::facts;
use super::destination::open_observation_pool;
use super::harness::DESTINATION;

const OBSERVER: &str = "act1-destination-reader-v1";
pub type Driver = GoalCheckedActionSkillDriver<Destination, Observer>;

pub fn contract() -> ActionSkillContractV1 {
    ActionSkillContractV1 {
        schema_version: 1,
        skill_id: "act1.write-and-check".to_string(),
        version: 1,
        destination_id: DESTINATION.to_string(),
        observer_id: OBSERVER.to_string(),
        initiation_digest: Sha256Digest::for_bytes(b"destination exists; nonempty valid request"),
        policy_digest: Sha256Digest::for_bytes(b"invoke once; reconcile original identity"),
        termination_digest: Sha256Digest::for_bytes(b"worker exited or interruption confirmed"),
        goal_digest: Sha256Digest::for_bytes(
            b"business events equal ordered requested rows exactly",
        ),
        budget: ActionSkillBudgetV1 {
            max_wire_bytes: 16_384,
            provider_timeout_ms: 30_000,
            observer_timeout_ms: 5_000,
        },
        recovery: ActionSkillRecoveryV1::ReconcileOriginalIdentity,
    }
}

pub fn wire() -> Vec<u8> {
    contract()
        .encode_invocation(serde_json::to_vec(&Desired::standard()).expect("domain body"))
        .expect("bound invocation")
}

pub async fn driver(root: &Path, destination: Destination) -> Driver {
    GoalCheckedActionSkillDriver::new(contract(), destination, Observer::open(root).await)
        .expect("goal-checked official driver")
}

pub struct Observer {
    pool: SqlitePool,
    evidence_dir: PathBuf,
}

impl Observer {
    pub async fn open(root: &Path) -> Self {
        let evidence_dir = root.join("observations");
        std::fs::create_dir_all(&evidence_dir).expect("observation evidence directory");
        Self {
            pool: open_observation_pool(&root.join("destination.sqlite3")).await,
            evidence_dir,
        }
    }

    fn retain(&self, value: serde_json::Value) -> Sha256Digest {
        let bytes = serde_json::to_vec(&value).expect("observation evidence bytes");
        let digest = Sha256Digest::for_bytes(&bytes);
        let path = self.evidence_dir.join(format!("{}.json", digest.as_str()));
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(mut file) => {
                file.write_all(&bytes).expect("retain complete evidence");
                file.sync_all().expect("persist observation evidence");
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                assert_eq!(std::fs::read(path).expect("existing evidence"), bytes);
            }
            Err(error) => panic!("cannot retain observation evidence: {error}"),
        }
        digest
    }
}

impl ActionSkillObserver for Observer {
    fn observer_id(&self) -> &str {
        OBSERVER
    }

    async fn check_initiation(
        &self,
        binding: &ActionSkillBindingV1,
        body: &[u8],
    ) -> Result<ActionInitiationObservationV1, ActionSkillError> {
        let desired: Desired =
            serde_json::from_slice(body).map_err(|_| ActionSkillError::Observation)?;
        let tables: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'business_events'",
        )
        .fetch_one(&self.pool)
        .await
        .map_err(|_| ActionSkillError::Observation)?;
        let condition = if tables == 1 && !desired.rows.is_empty() {
            ActionConditionV1::Met
        } else {
            ActionConditionV1::Unmet
        };
        let evidence_digest = self.retain(serde_json::json!({
            "kind":"initiation", "binding":binding, "body":desired, "tables":tables,
        }));
        Ok(ActionInitiationObservationV1 {
            binding: binding.clone(),
            observer_id: OBSERVER.to_string(),
            evidence_digest,
            condition,
        })
    }

    async fn observe(
        &self,
        binding: &ActionSkillBindingV1,
        provider_receipt_digest: &Sha256Digest,
    ) -> Result<ActionSkillObservationV1, ActionSkillError> {
        let facts = facts(&self.pool, &binding.provider_intent.key)
            .await
            .ok_or(ActionSkillError::Observation)?;
        if facts.payload != binding.provider_intent.payload_sha256.as_str() {
            return Err(ActionSkillError::Observation);
        }
        let execution = match facts.phase.as_str() {
            "waiting_input" => ActionExecutionStateV1::WaitingForInput,
            "accepted" => ActionExecutionStateV1::Running,
            "rejected_tombstone" => ActionExecutionStateV1::NotStarted,
            "cancelled" => ActionExecutionStateV1::Interrupted,
            "completed" | "partial" | "rejected_partial" | "exited" => {
                ActionExecutionStateV1::Returned {
                    exit_code: facts
                        .exit_code
                        .map(|code| i32::try_from(code).expect("exit code")),
                }
            }
            _ => ActionExecutionStateV1::Unknown,
        };
        let goal = if facts.rows == facts.desired.rows {
            ActionGoalStateV1::Satisfied
        } else if facts.rows.is_empty() {
            ActionGoalStateV1::Unsatisfied
        } else {
            ActionGoalStateV1::Partial
        };
        let termination = match execution {
            ActionExecutionStateV1::Returned { .. } | ActionExecutionStateV1::Interrupted => {
                ActionConditionV1::Met
            }
            ActionExecutionStateV1::NotStarted if facts.phase == "rejected_tombstone" => {
                ActionConditionV1::Met
            }
            ActionExecutionStateV1::NotStarted
            | ActionExecutionStateV1::Running
            | ActionExecutionStateV1::WaitingForInput
            | ActionExecutionStateV1::Unknown => ActionConditionV1::Unmet,
        };
        let cancellation = if facts.phase == "cancelled" {
            ActionCancellationStateV1::Confirmed
        } else if facts.cancel_received {
            ActionCancellationStateV1::Requested
        } else {
            ActionCancellationStateV1::NotRequested
        };
        let absence_proof_digest = (facts.phase == "rejected_tombstone" && facts.rows.is_empty())
            .then(|| {
                self.retain(serde_json::json!({
                    "kind":"destination_rejection_tombstone", "binding":binding,
                    "payload":facts.payload, "phase":facts.phase, "business_events":facts.rows,
                }))
            });
        let evidence_digest = self.retain(serde_json::json!({
            "kind":"terminal_observation", "binding":binding,
            "provider_receipt_digest":provider_receipt_digest,
            "facts":facts, "execution":execution, "goal":goal,
            "termination":termination, "cancellation":cancellation, "absence_proof_digest":absence_proof_digest,
        }));
        Ok(ActionSkillObservationV1 {
            binding: binding.clone(),
            provider_receipt_digest: provider_receipt_digest.clone(),
            observer_id: OBSERVER.to_string(),
            evidence_digest,
            execution,
            cancellation,
            termination,
            goal,
            absence_proof_digest,
        })
    }
}
