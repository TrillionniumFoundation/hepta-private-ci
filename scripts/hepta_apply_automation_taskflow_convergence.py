#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent(content).lstrip())


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one anchor, found {count}: {old[:120]!r}")
    (ROOT / path).write_text(text.replace(old, new, 1))


def append_before(path: str, marker: str, addition: str) -> None:
    text = read(path)
    index = text.rfind(marker)
    if index < 0:
        raise SystemExit(f"{path}: missing marker {marker!r}")
    (ROOT / path).write_text(text[:index] + addition + text[index:])


write(
    "codex-rs/hepta-automation/migrations/0021_product_effect_preparation.sql",
    r'''
    -- Freeze the product-originated TaskFlow effect, provider identity and exact
    -- historical fence before a final-use grant can cross the provider boundary.
    CREATE TABLE automation_product_effect_preparations (
        owner_agent_id TEXT NOT NULL,
        operation_id TEXT NOT NULL CHECK (length(operation_id) BETWEEN 1 AND 256),
        attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
        run_id TEXT NOT NULL CHECK (length(run_id) BETWEEN 1 AND 256),
        step_id TEXT NOT NULL CHECK (length(step_id) BETWEEN 1 AND 256),
        intent_json TEXT NOT NULL CHECK (length(intent_json) BETWEEN 2 AND 65536),
        intent_digest TEXT NOT NULL CHECK (
            length(intent_digest) = 64 AND intent_digest NOT GLOB '*[^0-9a-f]*'
        ),
        payload_digest TEXT NOT NULL CHECK (
            length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'
        ),
        provider_scope TEXT NOT NULL CHECK (length(provider_scope) BETWEEN 1 AND 128),
        provider_key TEXT NOT NULL CHECK (length(provider_key) BETWEEN 1 AND 256),
        provider_profile_digest TEXT NOT NULL CHECK (
            length(provider_profile_digest) = 64 AND
            provider_profile_digest NOT GLOB '*[^0-9a-f]*'
        ),
        fence_owner_id TEXT NOT NULL CHECK (length(fence_owner_id) BETWEEN 1 AND 256),
        fence_owner_epoch INTEGER NOT NULL CHECK (fence_owner_epoch > 0),
        fence_generation INTEGER NOT NULL CHECK (fence_generation > 0),
        fence_token TEXT NOT NULL CHECK (length(fence_token) BETWEEN 1 AND 256),
        preparation_digest TEXT NOT NULL CHECK (
            length(preparation_digest) = 64 AND preparation_digest NOT GLOB '*[^0-9a-f]*'
        ),
        prepared_at_ms INTEGER NOT NULL CHECK (prepared_at_ms >= 0),
        PRIMARY KEY (owner_agent_id, operation_id, attempt),
        UNIQUE (owner_agent_id, run_id, step_id, attempt),
        FOREIGN KEY (owner_agent_id, run_id)
            REFERENCES taskflow_runs(owner_agent_id, run_id)
    );

    CREATE INDEX automation_product_effect_latest_idx
        ON automation_product_effect_preparations(
            owner_agent_id, operation_id, attempt DESC
        );

    CREATE TRIGGER automation_product_effect_preparations_no_update
    BEFORE UPDATE ON automation_product_effect_preparations
    BEGIN
        SELECT RAISE(ABORT, 'product effect preparations are immutable');
    END;

    CREATE TRIGGER automation_product_effect_preparations_no_delete
    BEFORE DELETE ON automation_product_effect_preparations
    BEGIN
        SELECT RAISE(ABORT, 'product effect preparations are immutable');
    END;

    DROP TRIGGER automation_meta_no_update;
    UPDATE automation_meta SET schema_version = 21 WHERE singleton = 1;
    CREATE TRIGGER automation_meta_no_update
    BEFORE UPDATE ON automation_meta
    BEGIN
        SELECT RAISE(ABORT, 'automation owner metadata is immutable');
    END;
    ''',
)

write(
    "codex-rs/hepta-automation/migrations/0022_threshold_circuit_runtime.sql",
    r'''
    -- Minimal real DecisionCell: immutable candidate parameters and durable
    -- per-run choices. Circuit progression remains in the existing TaskFlow owner.
    CREATE TABLE automation_threshold_circuit_candidates (
        owner_agent_id TEXT NOT NULL,
        circuit_id TEXT NOT NULL CHECK (length(circuit_id) BETWEEN 1 AND 256),
        version INTEGER NOT NULL CHECK (version > 0 AND version <= 4294967295),
        predecessor_digest TEXT,
        threshold_ppm INTEGER NOT NULL CHECK (threshold_ppm BETWEEN -1000000 AND 1000000),
        parameter_digest TEXT NOT NULL CHECK (
            length(parameter_digest) = 64 AND parameter_digest NOT GLOB '*[^0-9a-f]*'
        ),
        resource_profile_digest TEXT NOT NULL CHECK (
            length(resource_profile_digest) = 64 AND
            resource_profile_digest NOT GLOB '*[^0-9a-f]*'
        ),
        candidate_digest TEXT NOT NULL CHECK (
            length(candidate_digest) = 64 AND candidate_digest NOT GLOB '*[^0-9a-f]*'
        ),
        registered_at_ms INTEGER NOT NULL CHECK (registered_at_ms >= 0),
        PRIMARY KEY (owner_agent_id, circuit_id, version),
        UNIQUE (owner_agent_id, candidate_digest),
        CHECK (
            (version = 1 AND predecessor_digest IS NULL)
            OR
            (version > 1 AND length(predecessor_digest) = 64 AND
             predecessor_digest NOT GLOB '*[^0-9a-f]*')
        )
    );

    CREATE TABLE automation_threshold_circuit_decisions (
        owner_agent_id TEXT NOT NULL,
        run_id TEXT NOT NULL CHECK (length(run_id) BETWEEN 1 AND 256),
        circuit_id TEXT NOT NULL CHECK (length(circuit_id) BETWEEN 1 AND 256),
        circuit_version INTEGER NOT NULL CHECK (circuit_version > 0),
        candidate_digest TEXT NOT NULL CHECK (
            length(candidate_digest) = 64 AND candidate_digest NOT GLOB '*[^0-9a-f]*'
        ),
        context_digest TEXT NOT NULL CHECK (
            length(context_digest) = 64 AND context_digest NOT GLOB '*[^0-9a-f]*'
        ),
        input_ppm INTEGER NOT NULL CHECK (input_ppm BETWEEN -1000000 AND 1000000),
        threshold_ppm INTEGER NOT NULL CHECK (threshold_ppm BETWEEN -1000000 AND 1000000),
        route TEXT NOT NULL CHECK (route IN ('allow', 'deny')),
        decision_digest TEXT NOT NULL CHECK (
            length(decision_digest) = 64 AND decision_digest NOT GLOB '*[^0-9a-f]*'
        ),
        decided_at_ms INTEGER NOT NULL CHECK (decided_at_ms >= 0),
        PRIMARY KEY (owner_agent_id, run_id),
        FOREIGN KEY (owner_agent_id, circuit_id, circuit_version)
            REFERENCES automation_threshold_circuit_candidates(
                owner_agent_id, circuit_id, version
            )
    );

    CREATE INDEX automation_threshold_circuit_decision_candidate_idx
        ON automation_threshold_circuit_decisions(
            owner_agent_id, circuit_id, circuit_version, decided_at_ms
        );

    CREATE TRIGGER automation_threshold_circuit_candidates_no_update
    BEFORE UPDATE ON automation_threshold_circuit_candidates
    BEGIN
        SELECT RAISE(ABORT, 'threshold circuit candidates are immutable');
    END;

    CREATE TRIGGER automation_threshold_circuit_candidates_no_delete
    BEFORE DELETE ON automation_threshold_circuit_candidates
    BEGIN
        SELECT RAISE(ABORT, 'threshold circuit candidates are immutable');
    END;

    CREATE TRIGGER automation_threshold_circuit_decisions_no_update
    BEFORE UPDATE ON automation_threshold_circuit_decisions
    BEGIN
        SELECT RAISE(ABORT, 'threshold circuit decisions are immutable');
    END;

    CREATE TRIGGER automation_threshold_circuit_decisions_no_delete
    BEFORE DELETE ON automation_threshold_circuit_decisions
    BEGIN
        SELECT RAISE(ABORT, 'threshold circuit decisions are immutable');
    END;

    DROP TRIGGER automation_meta_no_update;
    UPDATE automation_meta SET schema_version = 22 WHERE singleton = 1;
    CREATE TRIGGER automation_meta_no_update
    BEFORE UPDATE ON automation_meta
    BEGIN
        SELECT RAISE(ABORT, 'automation owner metadata is immutable');
    END;
    ''',
)

write(
    "codex-rs/hepta-automation/src/threshold_circuit.rs",
    r'''
    //! Minimal durable DecisionCell hosted by the existing automation owner.
    //!
    //! This is not a second scheduler or graph runtime. It loads an immutable
    //! parameter candidate, makes one bounded decision, and records the exact
    //! choice before a caller uses the selected route.

    use codex_hepta_contracts::Sha256Digest;
    use serde::{Deserialize, Serialize};
    use sqlx::Row;

    use crate::{AutomationStore, TaskFlowError};

    pub const THRESHOLD_CIRCUIT_SCHEMA_VERSION: u32 = 1;
    const MAX_ID_BYTES: usize = 256;
    const MAX_ABS_PPM: i32 = 1_000_000;

    #[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
    #[serde(rename_all = "snake_case")]
    pub enum ThresholdCircuitRouteV1 {
        Allow,
        Deny,
    }

    impl ThresholdCircuitRouteV1 {
        fn as_str(self) -> &'static str {
            match self {
                Self::Allow => "allow",
                Self::Deny => "deny",
            }
        }

        fn parse(value: &str) -> Result<Self, TaskFlowError> {
            match value {
                "allow" => Ok(Self::Allow),
                "deny" => Ok(Self::Deny),
                _ => Err(corrupt("threshold circuit route")),
            }
        }
    }

    #[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
    #[serde(deny_unknown_fields)]
    pub struct ThresholdCircuitCandidateV1 {
        pub circuit_id: String,
        pub version: u32,
        pub predecessor_digest: Option<Sha256Digest>,
        pub threshold_ppm: i32,
        pub parameter_digest: Sha256Digest,
        pub resource_profile_digest: Sha256Digest,
        pub candidate_digest: Sha256Digest,
    }

    impl ThresholdCircuitCandidateV1 {
        pub fn new(
            circuit_id: impl Into<String>,
            version: u32,
            predecessor_digest: Option<Sha256Digest>,
            threshold_ppm: i32,
            parameter_digest: Sha256Digest,
            resource_profile_digest: Sha256Digest,
        ) -> Result<Self, TaskFlowError> {
            let mut candidate = Self {
                circuit_id: circuit_id.into(),
                version,
                predecessor_digest,
                threshold_ppm,
                parameter_digest,
                resource_profile_digest,
                candidate_digest: Sha256Digest::for_bytes(b"uncomputed-threshold-circuit"),
            };
            candidate.validate_shape()?;
            candidate.candidate_digest = candidate.compute_digest();
            Ok(candidate)
        }

        pub fn validate(&self) -> Result<(), TaskFlowError> {
            self.validate_shape()?;
            if self.candidate_digest != self.compute_digest() {
                return Err(corrupt("threshold circuit candidate digest"));
            }
            Ok(())
        }

        fn validate_shape(&self) -> Result<(), TaskFlowError> {
            validate_id(&self.circuit_id, "circuit_id")?;
            if self.version == 0 || self.threshold_ppm.unsigned_abs() > MAX_ABS_PPM as u32 {
                return Err(invalid("invalid threshold circuit version or threshold"));
            }
            match (self.version, self.predecessor_digest.as_ref()) {
                (1, None) => {}
                (1, Some(_)) => return Err(invalid("v1 threshold circuit has a predecessor")),
                (_, None) => return Err(invalid("threshold circuit successor needs a predecessor")),
                (_, Some(_)) => {}
            }
            validate_digest(&self.parameter_digest, "parameter_digest")?;
            validate_digest(&self.resource_profile_digest, "resource_profile_digest")?;
            Ok(())
        }

        fn compute_digest(&self) -> Sha256Digest {
            let mut bytes = b"hepta.automation.threshold-circuit.candidate.v1\0".to_vec();
            push_text(&mut bytes, &self.circuit_id);
            bytes.extend_from_slice(&self.version.to_be_bytes());
            match &self.predecessor_digest {
                Some(digest) => {
                    bytes.push(1);
                    bytes.extend_from_slice(digest.as_str().as_bytes());
                }
                None => bytes.push(0),
            }
            bytes.extend_from_slice(&self.threshold_ppm.to_be_bytes());
            bytes.extend_from_slice(self.parameter_digest.as_str().as_bytes());
            bytes.extend_from_slice(self.resource_profile_digest.as_str().as_bytes());
            Sha256Digest::for_bytes(&bytes)
        }
    }

    #[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
    #[serde(deny_unknown_fields)]
    pub struct ThresholdCircuitInvocationV1 {
        pub run_id: String,
        pub circuit_id: String,
        pub circuit_version: u32,
        pub context_digest: Sha256Digest,
        pub input_ppm: i32,
    }

    #[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
    #[serde(deny_unknown_fields)]
    pub struct ThresholdCircuitDecisionV1 {
        pub run_id: String,
        pub circuit_id: String,
        pub circuit_version: u32,
        pub candidate_digest: Sha256Digest,
        pub context_digest: Sha256Digest,
        pub input_ppm: i32,
        pub threshold_ppm: i32,
        pub route: ThresholdCircuitRouteV1,
        pub decision_digest: Sha256Digest,
        pub decided_at_ms: u64,
    }

    impl AutomationStore {
        pub async fn register_threshold_circuit_candidate(
            &self,
            candidate: &ThresholdCircuitCandidateV1,
            registered_at_ms: u64,
        ) -> Result<ThresholdCircuitCandidateV1, TaskFlowError> {
            candidate.validate()?;
            if candidate.version > 1 {
                let predecessor = self
                    .threshold_circuit_candidate(&candidate.circuit_id, candidate.version - 1)
                    .await?
                    .ok_or_else(|| invalid("threshold circuit predecessor is missing"))?;
                if candidate.predecessor_digest.as_ref() != Some(&predecessor.candidate_digest) {
                    return Err(TaskFlowError::Conflict(
                        "threshold circuit predecessor does not match current candidate".to_string(),
                    ));
                }
            }
            let inserted = sqlx::query(
                "INSERT INTO automation_threshold_circuit_candidates (
                    owner_agent_id, circuit_id, version, predecessor_digest, threshold_ppm,
                    parameter_digest, resource_profile_digest, candidate_digest, registered_at_ms
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(&candidate.circuit_id)
            .bind(i64::from(candidate.version))
            .bind(candidate.predecessor_digest.as_ref().map(Sha256Digest::as_str))
            .bind(i64::from(candidate.threshold_ppm))
            .bind(candidate.parameter_digest.as_str())
            .bind(candidate.resource_profile_digest.as_str())
            .bind(candidate.candidate_digest.as_str())
            .bind(to_i64(registered_at_ms)?)
            .execute(self.taskflow_pool())
            .await;
            match inserted {
                Ok(_) => Ok(candidate.clone()),
                Err(error) if is_constraint(&error) => {
                    let stored = self
                        .threshold_circuit_candidate(&candidate.circuit_id, candidate.version)
                        .await?
                        .ok_or_else(|| corrupt("threshold circuit candidate conflict"))?;
                    if stored == *candidate {
                        Ok(stored)
                    } else {
                        Err(TaskFlowError::Conflict(
                            "threshold circuit version is bound to different parameters".to_string(),
                        ))
                    }
                }
                Err(_) => Err(TaskFlowError::Unavailable),
            }
        }

        pub async fn threshold_circuit_candidate(
            &self,
            circuit_id: &str,
            version: u32,
        ) -> Result<Option<ThresholdCircuitCandidateV1>, TaskFlowError> {
            validate_id(circuit_id, "circuit_id")?;
            if version == 0 {
                return Err(invalid("threshold circuit version is zero"));
            }
            sqlx::query(
                "SELECT circuit_id, version, predecessor_digest, threshold_ppm,
                        parameter_digest, resource_profile_digest, candidate_digest
                 FROM automation_threshold_circuit_candidates
                 WHERE owner_agent_id = ? AND circuit_id = ? AND version = ?",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(circuit_id)
            .bind(i64::from(version))
            .fetch_optional(self.taskflow_pool())
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
            .map(candidate_from_row)
            .transpose()
        }

        pub async fn run_threshold_circuit(
            &self,
            invocation: &ThresholdCircuitInvocationV1,
            decided_at_ms: u64,
        ) -> Result<ThresholdCircuitDecisionV1, TaskFlowError> {
            validate_id(&invocation.run_id, "run_id")?;
            validate_id(&invocation.circuit_id, "circuit_id")?;
            validate_digest(&invocation.context_digest, "context_digest")?;
            if invocation.circuit_version == 0
                || invocation.input_ppm.unsigned_abs() > MAX_ABS_PPM as u32
            {
                return Err(invalid("invalid threshold circuit invocation"));
            }
            let candidate = self
                .threshold_circuit_candidate(&invocation.circuit_id, invocation.circuit_version)
                .await?
                .ok_or_else(|| TaskFlowError::Conflict("threshold circuit candidate is not registered".to_string()))?;
            let route = if invocation.input_ppm >= candidate.threshold_ppm {
                ThresholdCircuitRouteV1::Allow
            } else {
                ThresholdCircuitRouteV1::Deny
            };
            let decision_digest = decision_digest(invocation, &candidate, route);
            let decision = ThresholdCircuitDecisionV1 {
                run_id: invocation.run_id.clone(),
                circuit_id: invocation.circuit_id.clone(),
                circuit_version: invocation.circuit_version,
                candidate_digest: candidate.candidate_digest,
                context_digest: invocation.context_digest.clone(),
                input_ppm: invocation.input_ppm,
                threshold_ppm: candidate.threshold_ppm,
                route,
                decision_digest,
                decided_at_ms,
            };
            let inserted = sqlx::query(
                "INSERT INTO automation_threshold_circuit_decisions (
                    owner_agent_id, run_id, circuit_id, circuit_version, candidate_digest,
                    context_digest, input_ppm, threshold_ppm, route, decision_digest, decided_at_ms
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(&decision.run_id)
            .bind(&decision.circuit_id)
            .bind(i64::from(decision.circuit_version))
            .bind(decision.candidate_digest.as_str())
            .bind(decision.context_digest.as_str())
            .bind(i64::from(decision.input_ppm))
            .bind(i64::from(decision.threshold_ppm))
            .bind(decision.route.as_str())
            .bind(decision.decision_digest.as_str())
            .bind(to_i64(decision.decided_at_ms)?)
            .execute(self.taskflow_pool())
            .await;
            match inserted {
                Ok(_) => Ok(decision),
                Err(error) if is_constraint(&error) => {
                    let stored = self
                        .threshold_circuit_decision(&invocation.run_id)
                        .await?
                        .ok_or_else(|| corrupt("threshold circuit decision conflict"))?;
                    if stored == decision {
                        Ok(stored)
                    } else {
                        Err(TaskFlowError::Conflict(
                            "threshold circuit run is bound to a different choice".to_string(),
                        ))
                    }
                }
                Err(_) => Err(TaskFlowError::Unavailable),
            }
        }

        pub async fn threshold_circuit_decision(
            &self,
            run_id: &str,
        ) -> Result<Option<ThresholdCircuitDecisionV1>, TaskFlowError> {
            validate_id(run_id, "run_id")?;
            sqlx::query(
                "SELECT run_id, circuit_id, circuit_version, candidate_digest, context_digest,
                        input_ppm, threshold_ppm, route, decision_digest, decided_at_ms
                 FROM automation_threshold_circuit_decisions
                 WHERE owner_agent_id = ? AND run_id = ?",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(run_id)
            .fetch_optional(self.taskflow_pool())
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
            .map(decision_from_row)
            .transpose()
        }
    }

    fn candidate_from_row(row: sqlx::sqlite::SqliteRow) -> Result<ThresholdCircuitCandidateV1, TaskFlowError> {
        let version = u32::try_from(row.try_get::<i64, _>("version").map_err(|_| corrupt("candidate version"))?)
            .map_err(|_| corrupt("candidate version"))?;
        let candidate = ThresholdCircuitCandidateV1 {
            circuit_id: row.try_get("circuit_id").map_err(|_| corrupt("candidate id"))?,
            version,
            predecessor_digest: row
                .try_get::<Option<String>, _>("predecessor_digest")
                .map_err(|_| corrupt("candidate predecessor"))?
                .map(Sha256Digest::parse)
                .transpose()
                .map_err(|_| corrupt("candidate predecessor"))?,
            threshold_ppm: i32::try_from(row.try_get::<i64, _>("threshold_ppm").map_err(|_| corrupt("candidate threshold"))?)
                .map_err(|_| corrupt("candidate threshold"))?,
            parameter_digest: parse_digest(&row, "parameter_digest")?,
            resource_profile_digest: parse_digest(&row, "resource_profile_digest")?,
            candidate_digest: parse_digest(&row, "candidate_digest")?,
        };
        candidate.validate()?;
        Ok(candidate)
    }

    fn decision_from_row(row: sqlx::sqlite::SqliteRow) -> Result<ThresholdCircuitDecisionV1, TaskFlowError> {
        Ok(ThresholdCircuitDecisionV1 {
            run_id: row.try_get("run_id").map_err(|_| corrupt("decision run"))?,
            circuit_id: row.try_get("circuit_id").map_err(|_| corrupt("decision circuit"))?,
            circuit_version: u32::try_from(row.try_get::<i64, _>("circuit_version").map_err(|_| corrupt("decision version"))?)
                .map_err(|_| corrupt("decision version"))?,
            candidate_digest: parse_digest(&row, "candidate_digest")?,
            context_digest: parse_digest(&row, "context_digest")?,
            input_ppm: i32::try_from(row.try_get::<i64, _>("input_ppm").map_err(|_| corrupt("decision input"))?)
                .map_err(|_| corrupt("decision input"))?,
            threshold_ppm: i32::try_from(row.try_get::<i64, _>("threshold_ppm").map_err(|_| corrupt("decision threshold"))?)
                .map_err(|_| corrupt("decision threshold"))?,
            route: ThresholdCircuitRouteV1::parse(&row.try_get::<String, _>("route").map_err(|_| corrupt("decision route"))?)?,
            decision_digest: parse_digest(&row, "decision_digest")?,
            decided_at_ms: u64::try_from(row.try_get::<i64, _>("decided_at_ms").map_err(|_| corrupt("decision time"))?)
                .map_err(|_| corrupt("decision time"))?,
        })
    }

    fn decision_digest(
        invocation: &ThresholdCircuitInvocationV1,
        candidate: &ThresholdCircuitCandidateV1,
        route: ThresholdCircuitRouteV1,
    ) -> Sha256Digest {
        let mut bytes = b"hepta.automation.threshold-circuit.decision.v1\0".to_vec();
        push_text(&mut bytes, &invocation.run_id);
        push_text(&mut bytes, &invocation.circuit_id);
        bytes.extend_from_slice(&invocation.circuit_version.to_be_bytes());
        bytes.extend_from_slice(invocation.context_digest.as_str().as_bytes());
        bytes.extend_from_slice(&invocation.input_ppm.to_be_bytes());
        bytes.extend_from_slice(candidate.candidate_digest.as_str().as_bytes());
        bytes.extend_from_slice(candidate.parameter_digest.as_str().as_bytes());
        bytes.extend_from_slice(&candidate.threshold_ppm.to_be_bytes());
        bytes.push(match route { ThresholdCircuitRouteV1::Allow => 1, ThresholdCircuitRouteV1::Deny => 0 });
        Sha256Digest::for_bytes(&bytes)
    }

    fn parse_digest(row: &sqlx::sqlite::SqliteRow, key: &str) -> Result<Sha256Digest, TaskFlowError> {
        Sha256Digest::parse(row.try_get::<String, _>(key).map_err(|_| corrupt(key))?)
            .map_err(|_| corrupt(key))
    }

    fn validate_id(value: &str, field: &str) -> Result<(), TaskFlowError> {
        if value.is_empty() || value.len() > MAX_ID_BYTES || value.chars().any(char::is_control) {
            return Err(invalid(field));
        }
        Ok(())
    }

    fn validate_digest(digest: &Sha256Digest, field: &str) -> Result<(), TaskFlowError> {
        if digest.as_str().bytes().all(|byte| byte == b'0') {
            return Err(invalid(field));
        }
        Ok(())
    }

    fn push_text(bytes: &mut Vec<u8>, value: &str) {
        bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
        bytes.extend_from_slice(value.as_bytes());
    }

    fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
        i64::try_from(value).map_err(|_| invalid("timestamp overflow"))
    }

    fn is_constraint(error: &sqlx::Error) -> bool {
        matches!(error, sqlx::Error::Database(database) if database.is_unique_violation() || database.is_foreign_key_violation() || database.is_check_violation())
    }

    fn invalid(message: impl Into<String>) -> TaskFlowError {
        TaskFlowError::Invalid(message.into())
    }

    fn corrupt(message: impl Into<String>) -> TaskFlowError {
        TaskFlowError::Corrupt(message.into())
    }
    ''',
)

write(
    "codex-rs/hepta-automation/src/product_effect.rs",
    r'''
    //! Product-originated external-effect preparation and recovery.
    //!
    //! A normal Agentd request creates the existing TaskFlow run and claimed
    //! step, then freezes provider identity before final-use admission. Physical
    //! retries are allowed only after the local durable attempt table proves
    //! provider contact could not have happened.

    use codex_hepta_contracts::{
        FinalUseAuthority, FinalUseBinding, ProviderEffectIntent, ProviderEffectKey,
        Sha256Digest, SignedFinalUseGrant,
    };
    use serde::{Deserialize, Serialize};
    use sqlx::Row;

    use crate::authorized_effect::{
        AsyncAuthorizedEffectDriver, AuthorizedEffectError, final_use_binding_digest,
    };
    use crate::{
        AuthorizedEffectIntent, AutomationStore, TaskFlowCommand, TaskFlowDefinition,
        TaskFlowEdgeSpec, TaskFlowError, TaskFlowFence, TaskFlowNodeKind, TaskFlowNodeSpec,
        TaskFlowRunState, TaskFlowStepReceipt, TaskFlowStepState, TaskFlowTransition,
    };

    const PRODUCT_EFFECT_WORKFLOW_ID: &str = "agentd.product-effect.v1";
    const PRODUCT_EFFECT_STEP_ID: &str = "effect";
    const PRODUCT_EFFECT_CAPABILITY: &str = "provider.effect";
    const MAX_PROVIDER_SCOPE_BYTES: usize = 128;

    #[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
    #[serde(deny_unknown_fields)]
    pub struct ProductEffectPreparationRequestV1 {
        pub intent: AuthorizedEffectIntent,
        pub provider_scope: String,
        pub provider_profile_digest: Sha256Digest,
    }

    #[derive(Clone, Debug, Eq, PartialEq, Serialize)]
    pub struct ProductEffectPreparationV1 {
        pub intent: AuthorizedEffectIntent,
        pub intent_digest: Sha256Digest,
        pub provider_scope: String,
        pub provider_key: String,
        pub provider_profile_digest: Sha256Digest,
        pub fence: TaskFlowFence,
        pub preparation_digest: Sha256Digest,
        pub prepared_at_ms: u64,
    }

    impl AutomationStore {
        pub async fn prepare_product_effect_v1(
            &self,
            request: &ProductEffectPreparationRequestV1,
            fence: &TaskFlowFence,
            now_ms: u64,
            lease_duration_ms: u64,
        ) -> Result<ProductEffectPreparationV1, TaskFlowError> {
            validate_request(request, self, fence, lease_duration_ms)?;
            let intent_digest = request.intent.digest()?;
            let latest = self
                .latest_product_effect_preparation(&request.intent.operation_id)
                .await?;
            let (provider_scope, provider_key, provider_profile_digest) = match latest.as_ref() {
                Some(previous) if previous.intent.attempt == request.intent.attempt => {
                    let candidate = preparation(
                        request.intent.clone(),
                        intent_digest,
                        previous.provider_scope.clone(),
                        previous.provider_key.clone(),
                        previous.provider_profile_digest.clone(),
                        previous.fence.clone(),
                        previous.prepared_at_ms,
                    )?;
                    if candidate.intent == previous.intent
                        && candidate.intent_digest == previous.intent_digest
                        && candidate.provider_scope == previous.provider_scope
                        && candidate.provider_key == previous.provider_key
                        && candidate.provider_profile_digest == previous.provider_profile_digest
                    {
                        return Ok(previous.clone());
                    }
                    return Err(TaskFlowError::Conflict(
                        "product effect attempt is bound to different semantics".to_string(),
                    ));
                }
                Some(previous) => {
                    let expected = previous
                        .intent
                        .attempt
                        .checked_add(1)
                        .ok_or_else(|| TaskFlowError::Invalid("product effect attempt exhausted".to_string()))?;
                    if request.intent.attempt != expected || !same_logical_effect(&previous.intent, &request.intent) {
                        return Err(TaskFlowError::Conflict(
                            "product effect retry is not the exact next physical attempt".to_string(),
                        ));
                    }
                    if self
                        .authorized_taskflow_effect_attempt(
                            &previous.intent.run_id,
                            &previous.intent.step_id,
                            previous.intent.attempt,
                        )
                        .await
                        .map_err(|error| TaskFlowError::Conflict(error.to_string()))?
                        .is_some()
                    {
                        return Err(TaskFlowError::Conflict(
                            "provider contact is durable; reconcile instead of retrying".to_string(),
                        ));
                    }
                    self.requeue_uncontacted_product_attempt(
                        previous,
                        fence,
                        now_ms,
                        lease_duration_ms,
                    )
                    .await?;
                    (
                        previous.provider_scope.clone(),
                        previous.provider_key.clone(),
                        previous.provider_profile_digest.clone(),
                    )
                }
                None => {
                    if request.intent.attempt != 1 {
                        return Err(TaskFlowError::Conflict(
                            "first product effect attempt must be one".to_string(),
                        ));
                    }
                    let key = ProviderEffectKey::for_operation(
                        &request.provider_scope,
                        &request.intent.run_id,
                        &request.intent.step_id,
                    )
                    .map_err(|_| TaskFlowError::Invalid("provider effect key".to_string()))?;
                    (
                        request.provider_scope.clone(),
                        key.as_str().to_string(),
                        request.provider_profile_digest.clone(),
                    )
                }
            };

            let active_fence = self
                .prepare_product_run_and_step(
                    &request.intent,
                    &intent_digest,
                    fence,
                    now_ms,
                    lease_duration_ms,
                )
                .await?;
            let prepared = preparation(
                request.intent.clone(),
                intent_digest,
                provider_scope,
                provider_key,
                provider_profile_digest,
                active_fence,
                now_ms,
            )?;
            self.insert_product_effect_preparation(&prepared).await
        }

        pub async fn latest_product_effect_preparation(
            &self,
            operation_id: &str,
        ) -> Result<Option<ProductEffectPreparationV1>, TaskFlowError> {
            if operation_id.is_empty() || operation_id.len() > 256 {
                return Err(TaskFlowError::Invalid("product effect operation id".to_string()));
            }
            sqlx::query(
                "SELECT * FROM automation_product_effect_preparations
                 WHERE owner_agent_id = ? AND operation_id = ?
                 ORDER BY attempt DESC LIMIT 1",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(operation_id)
            .fetch_optional(self.taskflow_pool())
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
            .map(|row| preparation_from_row(self, row))
            .transpose()
        }

        pub async fn product_effect_preparation(
            &self,
            run_id: &str,
            step_id: &str,
            attempt: u32,
        ) -> Result<Option<ProductEffectPreparationV1>, TaskFlowError> {
            sqlx::query(
                "SELECT * FROM automation_product_effect_preparations
                 WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ?",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(run_id)
            .bind(step_id)
            .bind(i64::from(attempt))
            .fetch_optional(self.taskflow_pool())
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
            .map(|row| preparation_from_row(self, row))
            .transpose()
        }

        #[allow(clippy::too_many_arguments)]
        pub async fn execute_prepared_product_effect_async<D: AsyncAuthorizedEffectDriver>(
            &self,
            authority: &FinalUseAuthority,
            driver: &mut D,
            prepared: &ProductEffectPreparationV1,
            wire_payload: &[u8],
            signed_grant: &SignedFinalUseGrant,
            command_id: &str,
            now_ms: u64,
        ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
            let stored = self
                .product_effect_preparation(
                    &prepared.intent.run_id,
                    &prepared.intent.step_id,
                    prepared.intent.attempt,
                )
                .await?
                .ok_or_else(|| TaskFlowError::Conflict("product effect is not prepared".to_string()))?;
            if stored != *prepared
                || Sha256Digest::for_bytes(wire_payload) != prepared.intent.payload_digest
                || prepared.intent.digest()? != prepared.intent_digest
            {
                return Err(AuthorizedEffectError::BindingMismatch);
            }
            let key = ProviderEffectKey::parse(prepared.provider_key.clone())
                .map_err(|_| AuthorizedEffectError::BindingMismatch)?;
            let provider_intent = ProviderEffectIntent::new(key, prepared.intent.payload_digest.clone());
            let binding = prepared.intent.final_use_binding()?;
            self.execute_authorized_taskflow_effect_async_with_provider_intent(
                authority,
                driver,
                &prepared.intent,
                provider_intent,
                wire_payload,
                &prepared.fence,
                signed_grant,
                &binding,
                command_id,
                now_ms,
            )
            .await
        }

        async fn prepare_product_run_and_step(
            &self,
            intent: &AuthorizedEffectIntent,
            intent_digest: &Sha256Digest,
            fence: &TaskFlowFence,
            now_ms: u64,
            lease_duration_ms: u64,
        ) -> Result<TaskFlowFence, TaskFlowError> {
            let definition = product_effect_definition()?;
            match self
                .taskflow_definition(&definition.workflow_id, definition.version)
                .await?
            {
                Some(stored) if stored == definition => {}
                Some(_) => {
                    return Err(TaskFlowError::Conflict(
                        "product effect definition is bound to different bytes".to_string(),
                    ));
                }
                None => {
                    self.register_taskflow_definition(&definition, fence, now_ms)
                        .await?;
                }
            }
            if self.taskflow_run(&intent.run_id).await?.is_none() {
                self.create_taskflow_run(
                    &intent.run_id,
                    &definition.workflow_id,
                    definition.version,
                    definition.definition_digest(),
                    &intent.operation_id,
                    now_ms,
                )
                .await?;
            }
            let mut run = self
                .taskflow_run(&intent.run_id)
                .await?
                .ok_or_else(|| TaskFlowError::Corrupt("product effect run vanished".to_string()))?;
            let current = run.owner_id.as_deref() == Some(fence.owner_id.as_str())
                && run.owner_epoch == Some(fence.owner_epoch)
                && run.generation == Some(fence.generation)
                && run.fencing_token.as_deref() == Some(fence.fencing_token.as_str())
                && run.lease_expires_at_ms.is_some_and(|expires| expires > now_ms);
            if run.state == TaskFlowRunState::Queued || !current {
                run = self
                    .claim_taskflow_run(&intent.run_id, fence, now_ms, lease_duration_ms)
                    .await?;
            }
            if run.state == TaskFlowRunState::Queued {
                run = self
                    .apply_taskflow_command(&TaskFlowCommand::new(
                        &intent.run_id,
                        format!("product-effect:start:{}:{}", intent.operation_id, intent.attempt),
                        fence.clone(),
                        run.revision,
                        TaskFlowTransition::Start,
                        now_ms,
                    )?)
                    .await?
                    .run;
            }
            if run.state != TaskFlowRunState::Running {
                return Err(TaskFlowError::Conflict(
                    "product effect run is not running".to_string(),
                ));
            }
            let existing = self
                .read_taskflow_step(
                    &intent.run_id,
                    &intent.step_id,
                    intent.attempt,
                    fence,
                )
                .await?;
            if existing.is_none() {
                self.prepare_taskflow_step(
                    &intent.run_id,
                    &intent.step_id,
                    intent.attempt,
                    fence,
                    intent_digest,
                    &intent.payload_digest,
                    &format!("product-effect:prepare:{}:{}", intent.operation_id, intent.attempt),
                    now_ms,
                )
                .await?;
            }
            let step = self
                .read_taskflow_step(
                    &intent.run_id,
                    &intent.step_id,
                    intent.attempt,
                    fence,
                )
                .await?
                .ok_or_else(|| TaskFlowError::Corrupt("product effect step vanished".to_string()))?;
            match step.state {
                TaskFlowStepState::Prepared => {
                    self.claim_taskflow_step(
                        &intent.run_id,
                        &intent.step_id,
                        intent.attempt,
                        fence,
                        intent_digest,
                        &intent.payload_digest,
                        &format!("product-effect:claim:{}:{}", intent.operation_id, intent.attempt),
                        now_ms,
                    )
                    .await?;
                }
                TaskFlowStepState::Claimed => {}
                _ => {
                    return Err(TaskFlowError::Conflict(
                        "product effect physical attempt is already observed".to_string(),
                    ));
                }
            }
            Ok(fence.clone())
        }

        async fn requeue_uncontacted_product_attempt(
            &self,
            previous: &ProductEffectPreparationV1,
            current_fence: &TaskFlowFence,
            now_ms: u64,
            lease_duration_ms: u64,
        ) -> Result<(), TaskFlowError> {
            let proof = no_contact_proof(previous);
            self.cancel_taskflow_step_after_proven_absence(
                &previous.intent.run_id,
                &previous.intent.step_id,
                previous.intent.attempt,
                &previous.fence,
                &previous.intent_digest,
                &previous.intent.payload_digest,
                &format!("product-effect:no-contact:{}:{}", previous.intent.operation_id, previous.intent.attempt),
                &proof,
                now_ms,
            )
            .await?;
            let mut run = self
                .taskflow_run(&previous.intent.run_id)
                .await?
                .ok_or_else(|| TaskFlowError::Corrupt("product effect run vanished".to_string()))?;
            let current = run.owner_id.as_deref() == Some(current_fence.owner_id.as_str())
                && run.owner_epoch == Some(current_fence.owner_epoch)
                && run.generation == Some(current_fence.generation)
                && run.fencing_token.as_deref() == Some(current_fence.fencing_token.as_str())
                && run.lease_expires_at_ms.is_some_and(|expires| expires > now_ms);
            if !current {
                run = self
                    .claim_taskflow_run(
                        &previous.intent.run_id,
                        current_fence,
                        now_ms,
                        lease_duration_ms,
                    )
                    .await?;
            }
            if run.state != TaskFlowRunState::Queued {
                self.apply_taskflow_requeue_proven_absent(&TaskFlowCommand::new(
                    &previous.intent.run_id,
                    format!("product-effect:requeue:{}:{}", previous.intent.operation_id, previous.intent.attempt),
                    current_fence.clone(),
                    run.revision,
                    TaskFlowTransition::RequeueProvenAbsent { proof_digest: proof },
                    now_ms,
                )?)
                .await?;
            }
            Ok(())
        }

        async fn insert_product_effect_preparation(
            &self,
            prepared: &ProductEffectPreparationV1,
        ) -> Result<ProductEffectPreparationV1, TaskFlowError> {
            let intent_json = serde_json::to_string(&prepared.intent)
                .map_err(|_| TaskFlowError::Corrupt("product effect intent serialization".to_string()))?;
            let result = sqlx::query(
                "INSERT INTO automation_product_effect_preparations (
                    owner_agent_id, operation_id, attempt, run_id, step_id, intent_json,
                    intent_digest, payload_digest, provider_scope, provider_key,
                    provider_profile_digest, fence_owner_id, fence_owner_epoch,
                    fence_generation, fence_token, preparation_digest, prepared_at_ms
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(&prepared.intent.operation_id)
            .bind(i64::from(prepared.intent.attempt))
            .bind(&prepared.intent.run_id)
            .bind(&prepared.intent.step_id)
            .bind(intent_json)
            .bind(prepared.intent_digest.as_str())
            .bind(prepared.intent.payload_digest.as_str())
            .bind(&prepared.provider_scope)
            .bind(&prepared.provider_key)
            .bind(prepared.provider_profile_digest.as_str())
            .bind(&prepared.fence.owner_id)
            .bind(to_i64(prepared.fence.owner_epoch)?)
            .bind(to_i64(prepared.fence.generation)?)
            .bind(&prepared.fence.fencing_token)
            .bind(prepared.preparation_digest.as_str())
            .bind(to_i64(prepared.prepared_at_ms)?)
            .execute(self.taskflow_pool())
            .await;
            match result {
                Ok(_) => Ok(prepared.clone()),
                Err(error) if is_constraint(&error) => {
                    let stored = self
                        .product_effect_preparation(
                            &prepared.intent.run_id,
                            &prepared.intent.step_id,
                            prepared.intent.attempt,
                        )
                        .await?
                        .ok_or_else(|| TaskFlowError::Corrupt("product effect insert conflict".to_string()))?;
                    if stored == *prepared {
                        Ok(stored)
                    } else {
                        Err(TaskFlowError::Conflict(
                            "product effect preparation conflicts with durable bytes".to_string(),
                        ))
                    }
                }
                Err(_) => Err(TaskFlowError::Unavailable),
            }
        }
    }

    fn preparation(
        intent: AuthorizedEffectIntent,
        intent_digest: Sha256Digest,
        provider_scope: String,
        provider_key: String,
        provider_profile_digest: Sha256Digest,
        fence: TaskFlowFence,
        prepared_at_ms: u64,
    ) -> Result<ProductEffectPreparationV1, TaskFlowError> {
        let mut bytes = b"hepta.automation.product-effect.preparation.v1\0".to_vec();
        bytes.extend_from_slice(intent_digest.as_str().as_bytes());
        push_text(&mut bytes, &provider_scope);
        push_text(&mut bytes, &provider_key);
        bytes.extend_from_slice(provider_profile_digest.as_str().as_bytes());
        push_text(&mut bytes, &fence.owner_id);
        bytes.extend_from_slice(&fence.owner_epoch.to_be_bytes());
        bytes.extend_from_slice(&fence.generation.to_be_bytes());
        push_text(&mut bytes, &fence.fencing_token);
        Ok(ProductEffectPreparationV1 {
            intent,
            intent_digest,
            provider_scope,
            provider_key,
            provider_profile_digest,
            fence,
            preparation_digest: Sha256Digest::for_bytes(&bytes),
            prepared_at_ms,
        })
    }

    fn preparation_from_row(
        store: &AutomationStore,
        row: sqlx::sqlite::SqliteRow,
    ) -> Result<ProductEffectPreparationV1, TaskFlowError> {
        let intent: AuthorizedEffectIntent = serde_json::from_str(
            &row.try_get::<String, _>("intent_json")
                .map_err(|_| TaskFlowError::Corrupt("product effect intent json".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("product effect intent json".to_string()))?;
        let fence = TaskFlowFence::new(
            store.taskflow_owner_agent_id().clone(),
            row.try_get::<String, _>("fence_owner_id")
                .map_err(|_| TaskFlowError::Corrupt("product effect fence owner".to_string()))?,
            parse_u64(&row, "fence_owner_epoch")?,
            parse_u64(&row, "fence_generation")?,
            row.try_get::<String, _>("fence_token")
                .map_err(|_| TaskFlowError::Corrupt("product effect fence token".to_string()))?,
        )?;
        let prepared = ProductEffectPreparationV1 {
            intent,
            intent_digest: parse_digest(&row, "intent_digest")?,
            provider_scope: row.try_get("provider_scope").map_err(|_| TaskFlowError::Corrupt("product effect provider scope".to_string()))?,
            provider_key: row.try_get("provider_key").map_err(|_| TaskFlowError::Corrupt("product effect provider key".to_string()))?,
            provider_profile_digest: parse_digest(&row, "provider_profile_digest")?,
            fence,
            preparation_digest: parse_digest(&row, "preparation_digest")?,
            prepared_at_ms: parse_u64(&row, "prepared_at_ms")?,
        };
        let rebuilt = preparation(
            prepared.intent.clone(),
            prepared.intent_digest.clone(),
            prepared.provider_scope.clone(),
            prepared.provider_key.clone(),
            prepared.provider_profile_digest.clone(),
            prepared.fence.clone(),
            prepared.prepared_at_ms,
        )?;
        if rebuilt.preparation_digest != prepared.preparation_digest
            || prepared.intent.digest()? != prepared.intent_digest
        {
            return Err(TaskFlowError::Corrupt(
                "product effect preparation digest mismatch".to_string(),
            ));
        }
        Ok(prepared)
    }

    fn product_effect_definition() -> Result<TaskFlowDefinition, TaskFlowError> {
        TaskFlowDefinition::new(
            PRODUCT_EFFECT_WORKFLOW_ID,
            1,
            PRODUCT_EFFECT_STEP_ID,
            vec![
                TaskFlowNodeSpec::effect(
                    PRODUCT_EFFECT_STEP_ID,
                    PRODUCT_EFFECT_CAPABILITY,
                    "provider-effect-key-v1",
                ),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new(PRODUCT_EFFECT_STEP_ID, "success"),
                TaskFlowEdgeSpec::new(PRODUCT_EFFECT_STEP_ID, "failure"),
            ],
            vec![PRODUCT_EFFECT_CAPABILITY.to_string()],
            Sha256Digest::for_bytes(b"hepta.automation.product-effect.policy.v1"),
        )
    }

    fn validate_request(
        request: &ProductEffectPreparationRequestV1,
        store: &AutomationStore,
        fence: &TaskFlowFence,
        lease_duration_ms: u64,
    ) -> Result<(), TaskFlowError> {
        request.intent.digest()?;
        if request.intent.subject_id != store.taskflow_owner_agent_id().as_str()
            || request.intent.step_id != PRODUCT_EFFECT_STEP_ID
            || request.provider_scope.is_empty()
            || request.provider_scope.len() > MAX_PROVIDER_SCOPE_BYTES
            || lease_duration_ms == 0
            || fence.owner_agent_id != *store.taskflow_owner_agent_id()
            || request.provider_profile_digest.as_str().bytes().all(|byte| byte == b'0')
        {
            return Err(TaskFlowError::Invalid("invalid product effect preparation request".to_string()));
        }
        Ok(())
    }

    fn same_logical_effect(left: &AuthorizedEffectIntent, right: &AuthorizedEffectIntent) -> bool {
        left.run_id == right.run_id
            && left.step_id == right.step_id
            && left.operation_id == right.operation_id
            && left.subject_id == right.subject_id
            && left.destination_id == right.destination_id
            && left.payload_digest == right.payload_digest
            && left.final_use_scope_digest == right.final_use_scope_digest
            && left.policy_generation == right.policy_generation
            && left.expected_predecessor_digest == right.expected_predecessor_digest
            && left.dependencies == right.dependencies
            && left.compensation_for == right.compensation_for
    }

    fn no_contact_proof(prepared: &ProductEffectPreparationV1) -> Sha256Digest {
        let mut bytes = b"hepta.automation.product-effect.no-durable-attempt.v1\0".to_vec();
        bytes.extend_from_slice(prepared.preparation_digest.as_str().as_bytes());
        bytes.extend_from_slice(&prepared.intent.attempt.to_be_bytes());
        Sha256Digest::for_bytes(&bytes)
    }

    fn final_use_binding_digest_for(prepared: &ProductEffectPreparationV1) -> Result<Sha256Digest, TaskFlowError> {
        let binding: FinalUseBinding = prepared.intent.final_use_binding().map_err(|error| TaskFlowError::Invalid(error.to_string()))?;
        final_use_binding_digest(&binding).map_err(|error| TaskFlowError::Invalid(error.to_string()))
    }

    fn parse_digest(row: &sqlx::sqlite::SqliteRow, key: &str) -> Result<Sha256Digest, TaskFlowError> {
        Sha256Digest::parse(row.try_get::<String, _>(key).map_err(|_| TaskFlowError::Corrupt(key.to_string()))?)
            .map_err(|_| TaskFlowError::Corrupt(key.to_string()))
    }

    fn parse_u64(row: &sqlx::sqlite::SqliteRow, key: &str) -> Result<u64, TaskFlowError> {
        u64::try_from(row.try_get::<i64, _>(key).map_err(|_| TaskFlowError::Corrupt(key.to_string()))?)
            .map_err(|_| TaskFlowError::Corrupt(key.to_string()))
    }

    fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
        i64::try_from(value).map_err(|_| TaskFlowError::Invalid("integer overflow".to_string()))
    }

    fn push_text(bytes: &mut Vec<u8>, value: &str) {
        bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
        bytes.extend_from_slice(value.as_bytes());
    }

    fn is_constraint(error: &sqlx::Error) -> bool {
        matches!(error, sqlx::Error::Database(database) if database.is_unique_violation() || database.is_foreign_key_violation() || database.is_check_violation())
    }
    ''',
)

# lib.rs module/export/schema convergence.
replace_once(
    "codex-rs/hepta-automation/src/lib.rs",
    "mod operation_destination;\n",
    "mod operation_destination;\nmod product_effect;\n",
)
replace_once(
    "codex-rs/hepta-automation/src/lib.rs",
    "mod taskflow_step;\nmod timer_lifecycle;\n",
    "mod taskflow_step;\nmod threshold_circuit;\nmod timer_lifecycle;\n",
)
replace_once(
    "codex-rs/hepta-automation/src/lib.rs",
    "pub use operation_destination::automation_task_payload_digest;\n",
    "pub use operation_destination::automation_task_payload_digest;\n"
    "pub use product_effect::ProductEffectPreparationRequestV1;\n"
    "pub use product_effect::ProductEffectPreparationV1;\n",
)
replace_once(
    "codex-rs/hepta-automation/src/lib.rs",
    "pub use taskflow_step::TaskFlowStepState;\n",
    "pub use taskflow_step::TaskFlowStepState;\n"
    "pub use threshold_circuit::THRESHOLD_CIRCUIT_SCHEMA_VERSION;\n"
    "pub use threshold_circuit::ThresholdCircuitCandidateV1;\n"
    "pub use threshold_circuit::ThresholdCircuitDecisionV1;\n"
    "pub use threshold_circuit::ThresholdCircuitInvocationV1;\n"
    "pub use threshold_circuit::ThresholdCircuitRouteV1;\n",
)
replace_once(
    "codex-rs/hepta-automation/src/lib.rs",
    "pub const AUTOMATION_SCHEMA_VERSION: u32 = 20;",
    "pub const AUTOMATION_SCHEMA_VERSION: u32 = 22;",
)

# Allow the prepared product path to pass the frozen provider key into the
# already-qualified async final-use boundary.
replace_once(
    "codex-rs/hepta-automation/src/authorized_effect.rs",
    "fn final_use_binding_digest(\n",
    "pub(crate) fn final_use_binding_digest(\n",
)
old_async = '''    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {\n        let provider_intent = provider_effect_intent(intent, wire_payload)?;\n        let operation_intent = intent.operation_intent_v1()?;\n'''
new_async = '''    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {\n        let provider_intent = provider_effect_intent(intent, wire_payload)?;\n        self.execute_authorized_taskflow_effect_async_with_provider_intent(\n            authority,\n            driver,\n            intent,\n            provider_intent,\n            wire_payload,\n            fence,\n            signed_grant,\n            expected_binding,\n            command_id,\n            now_ms,\n        )\n        .await\n    }\n\n    #[allow(clippy::too_many_arguments)]\n    pub(crate) async fn execute_authorized_taskflow_effect_async_with_provider_intent<\n        D: AsyncAuthorizedEffectDriver,\n    >(\n        &self,\n        authority: &FinalUseAuthority,\n        driver: &mut D,\n        intent: &AuthorizedEffectIntent,\n        provider_intent: ProviderEffectIntent,\n        wire_payload: &[u8],\n        fence: &TaskFlowFence,\n        signed_grant: &SignedFinalUseGrant,\n        expected_binding: &FinalUseBinding,\n        command_id: &str,\n        now_ms: u64,\n    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {\n        if provider_intent.payload_sha256 != intent.payload_digest\n            || Sha256Digest::for_bytes(wire_payload) != intent.payload_digest\n        {\n            return Err(AuthorizedEffectError::BindingMismatch);\n        }\n        let operation_intent = intent.operation_intent_v1()?;\n'''
replace_once("codex-rs/hepta-automation/src/authorized_effect.rs", old_async, new_async)

# The product module no longer needs this dead helper after the final code is
# generated; keep its binding digest available for future migration validation.
# (No call-site suppression is added; strict lint will catch drift.)

write(
    "codex-rs/hepta-automation/tests/threshold_circuit.rs",
    r'''
    #![allow(clippy::expect_used, reason = "fixed qualification fixtures fail loudly")]

    use codex_hepta_automation::{
        AutomationStore, ThresholdCircuitCandidateV1, ThresholdCircuitInvocationV1,
        ThresholdCircuitRouteV1,
    };
    use codex_hepta_contracts::{AgentId, Sha256Digest};
    use codex_hepta_fleet::{AgentManifest, FleetRegistry, ResourceBudget, WorkspaceBinding};
    use codex_hepta_paths::{HeptaAgentLayout, HeptaFleetRoot};

    fn fixture() -> (tempfile::TempDir, HeptaAgentLayout) {
        let temp = tempfile::tempdir().expect("temp");
        let root = temp.path().canonicalize().expect("root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
            WorkspaceBinding::new(workspace.canonicalize().expect("workspace"), &fleet_root)
                .expect("binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register").layout;
        (temp, layout)
    }

    fn candidate(version: u32, predecessor: Option<Sha256Digest>, threshold: i32) -> ThresholdCircuitCandidateV1 {
        ThresholdCircuitCandidateV1::new(
            "delivery-threshold",
            version,
            predecessor,
            threshold,
            Sha256Digest::for_bytes(format!("parameters-{version}-{threshold}").as_bytes()),
            Sha256Digest::for_bytes(b"threshold-circuit-resource-profile"),
        )
        .expect("candidate")
    }

    fn invocation(run_id: &str, version: u32, input: i32) -> ThresholdCircuitInvocationV1 {
        ThresholdCircuitInvocationV1 {
            run_id: run_id.to_string(),
            circuit_id: "delivery-threshold".to_string(),
            circuit_version: version,
            context_digest: Sha256Digest::for_bytes(run_id.as_bytes()),
            input_ppm: input,
        }
    }

    #[tokio::test]
    async fn parameters_change_real_route_and_old_choice_survives_restart() {
        let (_temp, layout) = fixture();
        let store = AutomationStore::open(&layout).await.expect("store");
        let v1 = candidate(1, None, 500_000);
        store.register_threshold_circuit_candidate(&v1, 1).await.expect("v1");
        let first = store.run_threshold_circuit(&invocation("run-v1", 1, 600_000), 2).await.expect("first");
        assert_eq!(first.route, ThresholdCircuitRouteV1::Allow);
        store.close().await;

        let store = AutomationStore::open(&layout).await.expect("reopen");
        assert_eq!(store.threshold_circuit_decision("run-v1").await.expect("read"), Some(first.clone()));
        let replay = store.run_threshold_circuit(&invocation("run-v1", 1, 600_000), 2).await.expect("replay");
        assert_eq!(replay, first);

        let v2 = candidate(2, Some(v1.candidate_digest.clone()), 700_000);
        store.register_threshold_circuit_candidate(&v2, 3).await.expect("v2");
        let second = store.run_threshold_circuit(&invocation("run-v2", 2, 600_000), 4).await.expect("second");
        assert_eq!(second.route, ThresholdCircuitRouteV1::Deny);
        assert_eq!(store.threshold_circuit_decision("run-v1").await.expect("old"), Some(first));
    }

    #[tokio::test]
    async fn bounded_capacity_uses_exact_indexed_decisions_on_ordinary_disk() {
        let (_temp, layout) = fixture();
        let store = AutomationStore::open(&layout).await.expect("store");
        let v1 = candidate(1, None, 0);
        store.register_threshold_circuit_candidate(&v1, 1).await.expect("candidate");
        let started = std::time::Instant::now();
        for index in 0..256_u32 {
            let run_id = format!("capacity-{index:04}");
            let decision = store
                .run_threshold_circuit(&invocation(&run_id, 1, index as i32 - 128), u64::from(index) + 2)
                .await
                .expect("decision");
            assert_eq!(decision.run_id, run_id);
        }
        let elapsed = started.elapsed();
        eprintln!("threshold_capacity decisions=256 elapsed_ms={}", elapsed.as_millis());
        assert!(store.threshold_circuit_decision("capacity-0255").await.expect("lookup").is_some());
    }
    ''',
)

write(
    "codex-rs/hepta-automation/tests/product_effect.rs",
    r'''
    #![cfg(unix)]
    #![allow(clippy::expect_used, reason = "fixed qualification fixtures fail loudly")]

    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::atomic::{AtomicUsize, Ordering};

    use codex_hepta_automation::{
        AuthorizedEffectIntent, AutomationStore, ProductEffectPreparationRequestV1,
        ProviderEffectTaskFlowDriver, TaskFlowFence,
    };
    use codex_hepta_contracts::{
        AgentId, FinalUseAuthority, FinalUseGrant, FinalUseRevocations, ProviderEffectAck,
        ProviderEffectAckStatus, ProviderEffectAdapter, ProviderEffectDispatch, ProviderEffectFuture,
        ProviderEffectIdempotencyCapability, ProviderEffectIntent, ProviderEffectLookup, Sha256Digest,
        SignedFinalUseGrant,
    };
    use codex_hepta_fleet::{AgentManifest, FleetRegistry, ResourceBudget, WorkspaceBinding};
    use codex_hepta_paths::{HeptaAgentLayout, HeptaFleetRoot};
    use ed25519_dalek::{Signer, SigningKey};

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
    const WIRE: &[u8] = b"product-effect-wire";

    fn fixture() -> (tempfile::TempDir, HeptaAgentLayout) {
        let temp = tempfile::tempdir().expect("temp");
        let root = temp.path().canonicalize().expect("root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent"),
            WorkspaceBinding::new(workspace.canonicalize().expect("workspace"), &fleet_root)
                .expect("binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register").layout;
        (temp, layout)
    }

    fn fence(generation: u64) -> TaskFlowFence {
        TaskFlowFence::new(
            AgentId::parse(AGENT_ID).expect("agent"),
            "agentd-effect-host",
            generation,
            generation,
            format!("agentd-effect-host-{generation}"),
        )
        .expect("fence")
    }

    fn intent(attempt: u32) -> AuthorizedEffectIntent {
        AuthorizedEffectIntent {
            run_id: "product-effect-run".to_string(),
            step_id: "effect".to_string(),
            attempt,
            operation_id: "product-effect-operation".to_string(),
            subject_id: AGENT_ID.to_string(),
            destination_id: "provider:delivery".to_string(),
            payload_digest: Sha256Digest::for_bytes(WIRE),
            final_use_scope_digest: Sha256Digest::for_bytes(b"product-effect-scope"),
            policy_generation: 1,
            expected_predecessor_digest: None,
            dependencies: Vec::new(),
            compensation_for: None,
        }
    }

    fn request(attempt: u32, profile: &Sha256Digest) -> ProductEffectPreparationRequestV1 {
        ProductEffectPreparationRequestV1 {
            intent: intent(attempt),
            provider_scope: "provider/delivery-v1".to_string(),
            provider_profile_digest: profile.clone(),
        }
    }

    struct Adapter {
        calls: AtomicUsize,
    }

    impl ProviderEffectAdapter for Adapter {
        fn capability(&self) -> ProviderEffectIdempotencyCapability {
            ProviderEffectIdempotencyCapability::KeyAndStatusLookup
        }

        fn dispatch<'a>(&'a self, _intent: &'a ProviderEffectIntent) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
            Box::pin(async { ProviderEffectDispatch::Unknown })
        }

        fn dispatch_with_payload<'a>(
            &'a self,
            intent: &'a ProviderEffectIntent,
            payload: &'a [u8],
        ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            let ack = ProviderEffectAck {
                key: intent.key.clone(),
                payload_sha256: Sha256Digest::for_bytes(payload),
                provider_operation_id_sha256: Sha256Digest::for_bytes(b"provider-operation"),
                status: ProviderEffectAckStatus::Completed,
            };
            Box::pin(async move { ProviderEffectDispatch::Ack(ack) })
        }

        fn lookup<'a>(&'a self, _key: &'a codex_hepta_contracts::ProviderEffectKey) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
            Box::pin(async { ProviderEffectLookup::Unknown })
        }
    }

    fn signed_grant(intent: &AuthorizedEffectIntent) -> (FinalUseAuthority, SignedFinalUseGrant, tempfile::TempDir) {
        let key = SigningKey::from_bytes(&[71; 32]);
        let binding = intent.final_use_binding().expect("binding");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".to_string(),
            authority_epoch: 1,
            grant_id: format!("grant-{}", intent.attempt),
            nonce: [intent.attempt as u8; 32],
            binding,
            not_before_unix_ms: 0,
            expires_at_unix_ms: u64::MAX - 1,
        };
        let signature = key.sign(&grant.signing_bytes().expect("bytes")).to_bytes().to_vec();
        let dir = tempfile::tempdir().expect("authority");
        std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700)).expect("permissions");
        let authority = FinalUseAuthority::open_state_dir(
            dir.path(),
            "security-owner".to_string(),
            key.verifying_key().to_bytes(),
            FinalUseRevocations { authority_epoch: 1, revision: 1, revoked_grant_ids: BTreeSet::new() },
        )
        .expect("authority");
        (authority, SignedFinalUseGrant { grant, signature }, dir)
    }

    #[tokio::test]
    async fn normal_product_request_prepares_dispatches_and_replays_once() {
        let (_temp, layout) = fixture();
        let store = AutomationStore::open(&layout).await.expect("store");
        let profile = Sha256Digest::for_bytes(b"provider-profile-v1");
        let prepared = store.prepare_product_effect_v1(&request(1, &profile), &fence(1), 10, 50).await.expect("prepare");
        let adapter = Adapter { calls: AtomicUsize::new(0) };
        let mut driver = ProviderEffectTaskFlowDriver::new("provider:delivery".to_string(), adapter).expect("driver");
        let (authority, grant, _dir) = signed_grant(&prepared.intent);
        let first = store.execute_prepared_product_effect_async(&authority, &mut driver, &prepared, WIRE, &grant, "product-dispatch", 20).await.expect("dispatch");
        assert!(first.receipt_digest.is_some());
        let replay = store.execute_prepared_product_effect_async(&authority, &mut driver, &prepared, WIRE, &grant, "product-dispatch", 21).await.expect("replay");
        assert_eq!(replay, first);
        assert_eq!(driver.adapter().calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn restart_before_contact_requires_next_attempt_and_preserves_provider_identity() {
        let (_temp, layout) = fixture();
        let profile = Sha256Digest::for_bytes(b"provider-profile-v1");
        let store = AutomationStore::open(&layout).await.expect("store");
        let first = store.prepare_product_effect_v1(&request(1, &profile), &fence(1), 10, 5).await.expect("first");
        store.close().await;

        let store = AutomationStore::open(&layout).await.expect("reopen");
        let second = store.prepare_product_effect_v1(&request(2, &Sha256Digest::for_bytes(b"rotated-active-profile")), &fence(2), 100, 50).await.expect("second");
        assert_eq!(second.provider_key, first.provider_key);
        assert_eq!(second.provider_profile_digest, first.provider_profile_digest);
        assert_eq!(second.provider_scope, first.provider_scope);
        assert_eq!(second.intent.attempt, 2);
        assert!(store.authorized_taskflow_effect_attempt(&first.intent.run_id, &first.intent.step_id, 1).await.expect("attempt lookup").is_none());
    }

    #[tokio::test]
    async fn changed_payload_or_skipped_attempt_is_rejected_before_mutation() {
        let (_temp, layout) = fixture();
        let store = AutomationStore::open(&layout).await.expect("store");
        let profile = Sha256Digest::for_bytes(b"provider-profile-v1");
        store.prepare_product_effect_v1(&request(1, &profile), &fence(1), 10, 5).await.expect("first");
        assert!(store.prepare_product_effect_v1(&request(3, &profile), &fence(2), 100, 50).await.is_err());
        let mut changed = request(2, &profile);
        changed.intent.payload_digest = Sha256Digest::for_bytes(b"changed");
        assert!(store.prepare_product_effect_v1(&changed, &fence(2), 100, 50).await.is_err());
    }
    ''',
)

# Agentd protocol: additive real DecisionCell caller.
replace_once(
    "codex-rs/hepta-agent-protocol/src/capabilities.rs",
    'pub const AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT: &str = "automation.external_effect";\n',
    'pub const AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT: &str = "automation.external_effect";\n'
    'pub const AGENTD_CAPABILITY_AUTOMATION_THRESHOLD_CIRCUIT: &str = "automation.threshold_circuit";\n',
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "pub use capabilities::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT;\n",
    "pub use capabilities::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT;\n"
    "pub use capabilities::AGENTD_CAPABILITY_AUTOMATION_THRESHOLD_CIRCUIT;\n",
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "use codex_hepta_automation::AutomationTaskId;\n",
    "use codex_hepta_automation::AutomationTaskId;\n"
    "use codex_hepta_automation::ThresholdCircuitDecisionV1;\n"
    "use codex_hepta_automation::ThresholdCircuitInvocationV1;\n",
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    pub fn automation_list(request_id: u64, spawn_generation: u64, limit: u16) -> Self {\n",
    "    pub fn automation_run_threshold_circuit(\n"
    "        request_id: u64,\n"
    "        spawn_generation: u64,\n"
    "        invocation: ThresholdCircuitInvocationV1,\n"
    "    ) -> Self {\n"
    "        Self {\n"
    "            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,\n"
    "            request_id,\n"
    "            spawn_generation,\n"
    "            method: AgentdMethod::AutomationRunThresholdCircuit { invocation },\n"
    "        }\n"
    "    }\n\n"
    "    pub fn automation_list(request_id: u64, spawn_generation: u64, limit: u16) -> Self {\n",
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    AutomationReconcileEffect {\n        run_id: String,\n        step_id: String,\n        attempt: u32,\n    },\n",
    "    AutomationReconcileEffect {\n"
    "        run_id: String,\n"
    "        step_id: String,\n"
    "        attempt: u32,\n"
    "    },\n"
    "    AutomationRunThresholdCircuit {\n"
    "        invocation: ThresholdCircuitInvocationV1,\n"
    "    },\n",
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    AutomationEffectReconcile(AutomationEffectReconcileSnapshot),\n",
    "    AutomationEffectReconcile(AutomationEffectReconcileSnapshot),\n"
    "    AutomationThresholdCircuitDecision(ThresholdCircuitDecisionV1),\n",
)

# Agentd public re-exports, typed client and runtime control caller.
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use codex_hepta_agent_protocol::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT;\n",
    "pub use codex_hepta_agent_protocol::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT;\n"
    "pub use codex_hepta_agent_protocol::AGENTD_CAPABILITY_AUTOMATION_THRESHOLD_CIRCUIT;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use codex_hepta_automation::AutomationTimezoneTransitionV1;\n",
    "pub use codex_hepta_automation::AutomationTimezoneTransitionV1;\n"
    "pub use codex_hepta_automation::ThresholdCircuitCandidateV1;\n"
    "pub use codex_hepta_automation::ThresholdCircuitDecisionV1;\n"
    "pub use codex_hepta_automation::ThresholdCircuitInvocationV1;\n"
    "pub use codex_hepta_automation::ThresholdCircuitRouteV1;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/client.rs",
    "use codex_hepta_automation::AutomationTaskId;\n",
    "use codex_hepta_automation::AutomationTaskId;\n"
    "use codex_hepta_automation::ThresholdCircuitDecisionV1;\n"
    "use codex_hepta_automation::ThresholdCircuitInvocationV1;\n",
)
# Insert client method immediately before automation_list.
replace_once(
    "codex-rs/hepta-agentd/src/client.rs",
    "    pub async fn automation_list(&self, limit: u16) -> Result<Vec<AutomationTask>, AgentdError> {\n",
    "    pub async fn automation_run_threshold_circuit(\n"
    "        &self,\n"
    "        invocation: ThresholdCircuitInvocationV1,\n"
    "    ) -> Result<ThresholdCircuitDecisionV1, AgentdError> {\n"
    "        match self\n"
    "            .send(AgentdRequest::automation_run_threshold_circuit(\n"
    "                self.request_id(),\n"
    "                self.spawn_generation,\n"
    "                invocation,\n"
    "            ))\n"
    "            .await?\n"
    "            .payload\n"
    "        {\n"
    "            AgentdPayload::AutomationThresholdCircuitDecision(decision) => Ok(decision),\n"
    "            payload => unexpected(payload),\n"
    "        }\n"
    "    }\n\n"
    "    pub async fn automation_list(&self, limit: u16) -> Result<Vec<AutomationTask>, AgentdError> {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/state_control.rs",
    "                if self.automation_effect_host().is_some() {\n",
    "                if automation.is_some() {\n"
    "                    capabilities.push(\n"
    "                        crate::AgentdCapability::new(\n"
    "                            crate::AGENTD_CAPABILITY_AUTOMATION_THRESHOLD_CIRCUIT,\n"
    "                            1,\n"
    "                            0,\n"
    "                        )\n"
    "                        .map_err(AgentdError::Protocol)?,\n"
    "                    );\n"
    "                }\n"
    "                if self.automation_effect_host().is_some() {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/state_control.rs",
    "            crate::AgentdMethod::AutomationList { limit } => {\n",
    "            crate::AgentdMethod::AutomationRunThresholdCircuit { invocation } => {\n"
    "                require_automation_ready(\n"
    "                    lifecycle, app_server_ready, critical_stores_ready, revocation_ready,\n"
    "                    required_ports_ready, admission_open, fenced,\n"
    "                )?;\n"
    "                match automation {\n"
    "                    Some(store) => AgentdPayload::AutomationThresholdCircuitDecision(\n"
    "                        store\n"
    "                            .run_threshold_circuit(&invocation, now_ms()?)\n"
    "                            .await\n"
    "                            .map_err(|error| AgentdError::Protocol(error.to_string()))?,\n"
    "                    ),\n"
    "                    None => automation_unavailable(),\n"
    "                }\n"
    "            }\n"
    "            crate::AgentdMethod::AutomationList { limit } => {\n",
)
# Recovery remains available during an acknowledged drain.
replace_once(
    "codex-rs/hepta-agentd/src/state_control.rs",
    "            crate::AgentdMethod::AutomationReconcileEffect {\n                run_id,\n                step_id,\n                attempt,\n            } => {\n                require_automation_ready(\n                    lifecycle,\n                    app_server_ready,\n                    critical_stores_ready,\n                    revocation_ready,\n                    required_ports_ready,\n                    admission_open,\n                    fenced,\n                )?;\n",
    "            crate::AgentdMethod::AutomationReconcileEffect {\n"
    "                run_id,\n"
    "                step_id,\n"
    "                attempt,\n"
    "            } => {\n"
    "                require_automation_recovery_ready(lifecycle, critical_stores_ready, fenced)?;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/state_control.rs",
    "fn require_automation_ready(\n",
    "fn require_automation_recovery_ready(\n"
    "    lifecycle: AgentLifecycle,\n"
    "    critical_stores_ready: bool,\n"
    "    fenced: bool,\n"
    ") -> Result<(), AgentdError> {\n"
    "    if matches!(lifecycle, AgentLifecycle::Running | AgentLifecycle::Draining)\n"
    "        && critical_stores_ready\n"
    "        && !fenced\n"
    "    {\n"
    "        Ok(())\n"
    "    } else {\n"
    "        Err(AgentdError::Protocol(\n"
    "            \"automation recovery is unavailable for this Agent generation\".to_string(),\n"
    "        ))\n"
    "    }\n"
    "}\n\n"
    "fn require_automation_ready(\n",
)

# Replace the effect host with the current async/provider-profile product host.
write(
    "codex-rs/hepta-agentd/src/automation_effect_host.rs",
    r'''
    //! Host-owned composition for final-use-authorized automation effects.
    //!
    //! The active and bounded historical provider profiles are independently
    //! attested. Durable product preparation freezes the exact profile and key;
    //! restart reconciliation therefore never consults a new endpoint for an
    //! old effect identity.

    use std::collections::BTreeMap;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    use codex_hepta_automation::{
        AuthorizedEffectIntent, AuthorizedEffectPending, AuthorizedEffectProviderReceipt,
        AuthorizedEffectRecovery, AuthorizedEffectRecoveryResult, AutomationStore,
        ProductEffectPreparationRequestV1, ProductEffectPreparationV1,
        ProviderEffectTaskFlowDriver, TaskFlowFence, TaskFlowStepObservation,
        TaskFlowStepReceipt,
    };
    use codex_hepta_contracts::{
        FinalUseAuthority, FinalUseRevocations, ProviderEffectAck, ProviderEffectAckStatus,
        ProviderEffectAdapter, ProviderEffectIntent, ProviderEffectKey, ProviderEffectLookup,
        Sha256Digest, SignedFinalUseGrant,
    };
    use codex_model_provider::{
        HttpProviderEffectAdapter, HttpProviderEffectConfig,
        HttpProviderEffectContractAttestation,
    };
    use http::{HeaderMap, HeaderName, HeaderValue};
    use serde::Deserialize;

    use crate::{AgentdError, AgentdIdentity};

    const ACTIVE_SCHEMA_VERSION: u32 = 2;
    const LEGACY_SCHEMA_VERSION: u32 = 1;
    const MAX_HOST_FILE_BYTES: u64 = 256 * 1024;
    const MAX_REVOCATIONS_FILE_BYTES: u64 = 4 * 1024 * 1024;
    const MAX_PROVIDER_HEADERS: usize = 64;
    const MAX_RECOVERY_PROFILES: usize = 16;
    const PRODUCT_LEASE_MS: u64 = 30_000;

    #[derive(Clone, Debug)]
    pub(crate) enum AgentdAutomationEffectReconcileOutcome {
        Observed(Box<TaskFlowStepReceipt>),
        Indeterminate,
        ProvenAbsent,
    }

    #[derive(Clone)]
    struct ProviderProfile {
        provider_scope: String,
        destination_id: String,
        final_use_scope_digest: Sha256Digest,
        profile_digest: Sha256Digest,
        adapter: HttpProviderEffectAdapter,
    }

    #[derive(Clone)]
    pub(crate) struct AgentdAutomationEffectHost {
        agent_id: codex_hepta_contracts::AgentId,
        spawn_generation: u64,
        active: ProviderProfile,
        recovery_profiles: BTreeMap<String, ProviderProfile>,
        authority: FinalUseAuthority,
        revocations_file: PathBuf,
        revocation_frontier: Arc<Mutex<(u64, u64)>>,
    }

    impl std::fmt::Debug for AgentdAutomationEffectHost {
        fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter
                .debug_struct("AgentdAutomationEffectHost")
                .field("agent_id", &self.agent_id)
                .field("spawn_generation", &self.spawn_generation)
                .field("active_profile_digest", &self.active.profile_digest)
                .field("recovery_profile_count", &self.recovery_profiles.len())
                .finish_non_exhaustive()
        }
    }

    #[derive(Debug, Deserialize)]
    #[serde(deny_unknown_fields)]
    struct HostFile {
        schema_version: u32,
        provider_scope: String,
        destination_id: String,
        final_use_scope_sha256: String,
        dispatch_url: String,
        lookup_url_template: String,
        #[serde(default)]
        headers: BTreeMap<String, String>,
        timeout_ms: u64,
        contract_id: String,
        contract_sha256: String,
        contract_authority_epoch: u64,
        contract_signature_hex: String,
        contract_verifying_key_hex: String,
        final_use_signer_id: String,
        final_use_verifying_key_hex: String,
        final_use_revocations_file: PathBuf,
        #[serde(default)]
        recovery_profiles: Vec<ProviderProfileFile>,
    }

    #[derive(Debug, Deserialize)]
    #[serde(deny_unknown_fields)]
    struct ProviderProfileFile {
        provider_scope: String,
        destination_id: String,
        final_use_scope_sha256: String,
        dispatch_url: String,
        lookup_url_template: String,
        #[serde(default)]
        headers: BTreeMap<String, String>,
        timeout_ms: u64,
        contract_id: String,
        contract_sha256: String,
        contract_authority_epoch: u64,
        contract_signature_hex: String,
        contract_verifying_key_hex: String,
    }

    struct ProviderProfileView<'a> {
        provider_scope: &'a str,
        destination_id: &'a str,
        final_use_scope_sha256: &'a str,
        dispatch_url: &'a str,
        lookup_url_template: &'a str,
        headers: &'a BTreeMap<String, String>,
        timeout_ms: u64,
        contract_id: &'a str,
        contract_sha256: &'a str,
        contract_authority_epoch: u64,
        contract_signature_hex: &'a str,
        contract_verifying_key_hex: &'a str,
    }

    impl HostFile {
        fn active_view(&self) -> ProviderProfileView<'_> {
            ProviderProfileView {
                provider_scope: &self.provider_scope,
                destination_id: &self.destination_id,
                final_use_scope_sha256: &self.final_use_scope_sha256,
                dispatch_url: &self.dispatch_url,
                lookup_url_template: &self.lookup_url_template,
                headers: &self.headers,
                timeout_ms: self.timeout_ms,
                contract_id: &self.contract_id,
                contract_sha256: &self.contract_sha256,
                contract_authority_epoch: self.contract_authority_epoch,
                contract_signature_hex: &self.contract_signature_hex,
                contract_verifying_key_hex: &self.contract_verifying_key_hex,
            }
        }
    }

    impl ProviderProfileFile {
        fn view(&self) -> ProviderProfileView<'_> {
            ProviderProfileView {
                provider_scope: &self.provider_scope,
                destination_id: &self.destination_id,
                final_use_scope_sha256: &self.final_use_scope_sha256,
                dispatch_url: &self.dispatch_url,
                lookup_url_template: &self.lookup_url_template,
                headers: &self.headers,
                timeout_ms: self.timeout_ms,
                contract_id: &self.contract_id,
                contract_sha256: &self.contract_sha256,
                contract_authority_epoch: self.contract_authority_epoch,
                contract_signature_hex: &self.contract_signature_hex,
                contract_verifying_key_hex: &self.contract_verifying_key_hex,
            }
        }
    }

    impl AgentdAutomationEffectHost {
        pub(crate) fn open(identity: &AgentdIdentity, path: &Path) -> Result<Self, AgentdError> {
            let config: HostFile = serde_json::from_slice(&read_protected_file(path, MAX_HOST_FILE_BYTES, "automation effect host file")?)?;
            match config.schema_version {
                LEGACY_SCHEMA_VERSION if config.recovery_profiles.is_empty() => {}
                ACTIVE_SCHEMA_VERSION if config.recovery_profiles.len() <= MAX_RECOVERY_PROFILES => {}
                _ => return Err(AgentdError::Invalid("unsupported automation effect host schema or recovery profile bound".to_string())),
            }
            let active = open_profile(config.active_view())?;
            let mut recovery_profiles = BTreeMap::new();
            for profile in &config.recovery_profiles {
                let opened = open_profile(profile.view())?;
                if opened.profile_digest == active.profile_digest
                    || recovery_profiles.insert(opened.profile_digest.as_str().to_string(), opened).is_some()
                {
                    return Err(AgentdError::Invalid("duplicate automation effect provider profile".to_string()));
                }
            }
            let final_use_key = decode_hex_array::<32>(&config.final_use_verifying_key_hex, "final_use_verifying_key_hex")?;
            if !config.final_use_revocations_file.is_absolute() {
                return Err(AgentdError::Invalid("final_use_revocations_file must be absolute".to_string()));
            }
            let initial = read_revocations_file(&config.final_use_revocations_file)?;
            let frontier = (initial.authority_epoch, initial.revision);
            let authority_root = identity.layout.automation_root().join("final-use-authority");
            fs::create_dir_all(&authority_root)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(&authority_root, fs::Permissions::from_mode(0o700))?;
            }
            let authority = FinalUseAuthority::open_state_dir(
                &authority_root,
                config.final_use_signer_id,
                final_use_key,
                initial,
            )
            .map_err(|error| AgentdError::Protocol(format!("open automation final-use authority state: {error}")))?;
            Ok(Self {
                agent_id: identity.agent_id.clone(),
                spawn_generation: identity.spawn_generation,
                active,
                recovery_profiles,
                authority,
                revocations_file: config.final_use_revocations_file,
                revocation_frontier: Arc::new(Mutex::new(frontier)),
            })
        }

        pub(crate) async fn execute(
            &self,
            store: &AutomationStore,
            intent: &AuthorizedEffectIntent,
            wire_payload: &[u8],
            signed_grant: &SignedFinalUseGrant,
            command_id: &str,
            now_ms: u64,
        ) -> Result<TaskFlowStepReceipt, AgentdError> {
            self.validate_common(intent, wire_payload)?;
            self.refresh_revocations()?;
            let existing = store
                .latest_product_effect_preparation(&intent.operation_id)
                .await
                .map_err(taskflow_error)?;
            let profile = match existing.as_ref() {
                Some(prepared) => self.profile(&prepared.provider_profile_digest)?,
                None => &self.active,
            };
            validate_intent_profile(intent, profile)?;
            let request = ProductEffectPreparationRequestV1 {
                intent: intent.clone(),
                provider_scope: profile.provider_scope.clone(),
                provider_profile_digest: profile.profile_digest.clone(),
            };
            let prepared = store
                .prepare_product_effect_v1(
                    &request,
                    &self.host_fence()?,
                    now_ms,
                    PRODUCT_LEASE_MS,
                )
                .await
                .map_err(taskflow_error)?;
            if let Some(receipt) = store
                .read_authorized_taskflow_effect_receipt(&prepared.intent, command_id)
                .await
                .map_err(|error| AgentdError::Protocol(format!("read terminal effect receipt: {error}")))?
            {
                return Ok(receipt);
            }
            let mut driver = ProviderEffectTaskFlowDriver::new(
                prepared.intent.destination_id.clone(),
                profile.adapter.clone(),
            )
            .map_err(|error| AgentdError::Protocol(format!("build provider effect driver: {error}")))?;
            store
                .execute_prepared_product_effect_async(
                    &self.authority,
                    &mut driver,
                    &prepared,
                    wire_payload,
                    signed_grant,
                    command_id,
                    now_ms,
                )
                .await
                .map_err(|error| AgentdError::Protocol(format!("automation authorized effect dispatch: {error}")))
        }

        pub(crate) async fn reconcile(
            &self,
            store: &AutomationStore,
            run_id: &str,
            step_id: &str,
            attempt: u32,
            now_ms: u64,
        ) -> Result<AgentdAutomationEffectReconcileOutcome, AgentdError> {
            let pending = store
                .authorized_taskflow_effect_attempt(run_id, step_id, attempt)
                .await
                .map_err(|error| AgentdError::Protocol(format!("read pending authorized effect: {error}")))?
                .ok_or_else(|| AgentdError::Invalid("authorized effect is not pending reconciliation".to_string()))?;
            let prepared = store
                .product_effect_preparation(run_id, step_id, attempt)
                .await
                .map_err(taskflow_error)?;
            let (profile, provider_intent, fence) = match prepared {
                Some(prepared) => {
                    let profile = self.profile(&prepared.provider_profile_digest)?;
                    validate_intent_profile(&prepared.intent, profile)?;
                    if prepared.intent_digest != pending.intent_digest
                        || prepared.intent.payload_digest != pending.payload_digest
                        || prepared.intent.destination_id != pending.destination_id
                    {
                        return Err(AgentdError::GenerationFenced("pending effect differs from durable product preparation".to_string()));
                    }
                    let key = ProviderEffectKey::parse(prepared.provider_key)
                        .map_err(|error| AgentdError::Invalid(format!("stored provider key: {error:?}")))?;
                    (
                        profile,
                        ProviderEffectIntent::new(key, pending.payload_digest.clone()),
                        prepared.fence,
                    )
                }
                None => {
                    if pending.destination_id != self.active.destination_id {
                        return Err(AgentdError::GenerationFenced("legacy pending effect differs from active provider".to_string()));
                    }
                    let key = ProviderEffectKey::for_operation(
                        &self.active.provider_scope,
                        run_id,
                        step_id,
                    )
                    .map_err(|error| AgentdError::Invalid(format!("derive legacy provider key: {error:?}")))?;
                    let run = store.taskflow_run(run_id).await.map_err(taskflow_error)?
                        .ok_or_else(|| AgentdError::Invalid("effect TaskFlow run does not exist".to_string()))?;
                    (
                        &self.active,
                        ProviderEffectIntent::new(key, pending.payload_digest.clone()),
                        historical_fence(store, &run)?,
                    )
                }
            };
            if let Some(local) = store
                .settle_authorized_taskflow_effect_observation(run_id, step_id, attempt, &fence)
                .await
                .map_err(|error| AgentdError::Protocol(format!("settle durable effect observation: {error}")))?
            {
                match local {
                    AuthorizedEffectRecoveryResult::Observed(receipt)
                        if receipt.observation != Some(TaskFlowStepObservation::Indeterminate) =>
                    {
                        return Ok(AgentdAutomationEffectReconcileOutcome::Observed(Box::new(receipt)));
                    }
                    AuthorizedEffectRecoveryResult::ProvenAbsent => {
                        return Ok(AgentdAutomationEffectReconcileOutcome::ProvenAbsent);
                    }
                    AuthorizedEffectRecoveryResult::Observed(_) => {}
                }
            }
            match profile.adapter.lookup_for_intent(&provider_intent).await {
                ProviderEffectLookup::Ack(ack) => {
                    let Some(receipt) = terminal_receipt_from_ack(&ack, &provider_intent) else {
                        return Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate);
                    };
                    match store
                        .recover_authorized_taskflow_effect(
                            run_id,
                            step_id,
                            attempt,
                            &fence,
                            AuthorizedEffectRecovery::Observed(receipt),
                            now_ms,
                        )
                        .await
                        .map_err(|error| AgentdError::Protocol(format!("reconcile terminal effect: {error}")))?
                    {
                        AuthorizedEffectRecoveryResult::Observed(receipt) => Ok(
                            AgentdAutomationEffectReconcileOutcome::Observed(Box::new(receipt)),
                        ),
                        AuthorizedEffectRecoveryResult::ProvenAbsent => Err(AgentdError::Protocol(
                            "status lookup cannot manufacture provider absence".to_string(),
                        )),
                    }
                }
                ProviderEffectLookup::Conflict { .. } => Err(AgentdError::Protocol(
                    "provider reports a same-key payload conflict".to_string(),
                )),
                ProviderEffectLookup::NotFound | ProviderEffectLookup::Unknown => {
                    Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate)
                }
            }
        }

        fn profile(&self, digest: &Sha256Digest) -> Result<&ProviderProfile, AgentdError> {
            if &self.active.profile_digest == digest {
                return Ok(&self.active);
            }
            self.recovery_profiles.get(digest.as_str()).ok_or_else(|| {
                AgentdError::GenerationFenced(
                    "durable effect provider profile is not configured for recovery".to_string(),
                )
            })
        }

        fn host_fence(&self) -> Result<TaskFlowFence, AgentdError> {
            let mut bytes = b"hepta.agentd.automation-effect-host.fence.v1\0".to_vec();
            bytes.extend_from_slice(self.agent_id.as_str().as_bytes());
            bytes.extend_from_slice(&self.spawn_generation.to_be_bytes());
            TaskFlowFence::new(
                self.agent_id.clone(),
                "agentd.automation-effect-host",
                self.spawn_generation,
                self.spawn_generation,
                Sha256Digest::for_bytes(&bytes).as_str().to_string(),
            )
            .map_err(|error| AgentdError::Protocol(format!("build automation effect fence: {error}")))
        }

        fn refresh_revocations(&self) -> Result<(), AgentdError> {
            let head = read_revocations_file(&self.revocations_file)?;
            let mut frontier = self.revocation_frontier.lock().map_err(|_| {
                AgentdError::Protocol("automation effect revocation frontier lock is poisoned".to_string())
            })?;
            let observed = (head.authority_epoch, head.revision);
            if observed == *frontier {
                return Ok(());
            }
            if observed.0 < frontier.0 || (observed.0 == frontier.0 && observed.1 < frontier.1) {
                return Err(AgentdError::GenerationFenced("automation effect revocation frontier rolled back".to_string()));
            }
            self.authority.update_revocations(head).map_err(|error| {
                AgentdError::GenerationFenced(format!("automation effect revocation refresh rejected: {error}"))
            })?;
            *frontier = observed;
            Ok(())
        }

        fn validate_common(&self, intent: &AuthorizedEffectIntent, wire_payload: &[u8]) -> Result<(), AgentdError> {
            if wire_payload.is_empty() || wire_payload.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES {
                return Err(AgentdError::Invalid("automation effect wire payload is empty or too large".to_string()));
            }
            if intent.subject_id != self.agent_id.as_str()
                || Sha256Digest::for_bytes(wire_payload) != intent.payload_digest
            {
                return Err(AgentdError::GenerationFenced("automation effect subject or payload differs from the host".to_string()));
            }
            Ok(())
        }
    }

    fn open_profile(view: ProviderProfileView<'_>) -> Result<ProviderProfile, AgentdError> {
        validate_host_identifier("provider_scope", view.provider_scope)?;
        validate_host_identifier("destination_id", view.destination_id)?;
        if view.timeout_ms == 0 || view.timeout_ms > 30_000 || view.headers.len() > MAX_PROVIDER_HEADERS {
            return Err(AgentdError::Invalid("invalid provider timeout or header bound".to_string()));
        }
        let final_use_scope_digest = Sha256Digest::parse(view.final_use_scope_sha256.to_string())
            .map_err(AgentdError::Invalid)?;
        let contract_digest = Sha256Digest::parse(view.contract_sha256.to_string())
            .map_err(AgentdError::Invalid)?;
        let signature = decode_hex_array::<64>(view.contract_signature_hex, "contract_signature_hex")?;
        let verifying_key = decode_hex_array::<32>(view.contract_verifying_key_hex, "contract_verifying_key_hex")?;
        let mut headers = HeaderMap::new();
        for (name, value) in view.headers {
            headers.append(
                HeaderName::from_bytes(name.as_bytes()).map_err(|error| AgentdError::Invalid(format!("provider header name: {error}")))?,
                HeaderValue::from_bytes(value.as_bytes()).map_err(|error| AgentdError::Invalid(format!("provider header value: {error}")))?,
            );
        }
        let attestation = HttpProviderEffectContractAttestation::verify_signed(
            view.contract_id.to_string(),
            contract_digest,
            view.contract_authority_epoch,
            &signature,
            &verifying_key,
        )
        .map_err(AgentdError::Invalid)?;
        let adapter = HttpProviderEffectAdapter::new(HttpProviderEffectConfig {
            dispatch_url: view.dispatch_url.to_string(),
            lookup_url_template: view.lookup_url_template.to_string(),
            headers,
            timeout: Duration::from_millis(view.timeout_ms),
            contract_id: view.contract_id.to_string(),
            attestation: Some(attestation),
        })
        .map_err(AgentdError::Invalid)?;
        let profile_digest = profile_digest(&view, &final_use_scope_digest, &verifying_key);
        Ok(ProviderProfile {
            provider_scope: view.provider_scope.to_string(),
            destination_id: view.destination_id.to_string(),
            final_use_scope_digest,
            profile_digest,
            adapter,
        })
    }

    fn profile_digest(
        view: &ProviderProfileView<'_>,
        scope: &Sha256Digest,
        verifying_key: &[u8; 32],
    ) -> Sha256Digest {
        let mut bytes = b"hepta.agentd.automation-effect-provider-profile.v1\0".to_vec();
        for value in [
            view.provider_scope,
            view.destination_id,
            scope.as_str(),
            view.dispatch_url,
            view.lookup_url_template,
            view.contract_id,
            view.contract_sha256,
        ] {
            bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
            bytes.extend_from_slice(value.as_bytes());
        }
        bytes.extend_from_slice(&view.timeout_ms.to_be_bytes());
        bytes.extend_from_slice(&view.contract_authority_epoch.to_be_bytes());
        bytes.extend_from_slice(verifying_key);
        for (name, value) in view.headers {
            bytes.extend_from_slice(name.as_bytes());
            bytes.push(0);
            bytes.extend_from_slice(Sha256Digest::for_bytes(value.as_bytes()).as_str().as_bytes());
            bytes.push(0);
        }
        Sha256Digest::for_bytes(&bytes)
    }

    fn validate_intent_profile(intent: &AuthorizedEffectIntent, profile: &ProviderProfile) -> Result<(), AgentdError> {
        if intent.destination_id != profile.destination_id
            || intent.final_use_scope_digest != profile.final_use_scope_digest
        {
            return Err(AgentdError::GenerationFenced(
                "automation effect intent differs from its frozen provider profile".to_string(),
            ));
        }
        Ok(())
    }

    fn historical_fence(
        store: &AutomationStore,
        run: &codex_hepta_automation::TaskFlowRun,
    ) -> Result<TaskFlowFence, AgentdError> {
        TaskFlowFence::new(
            store.owner_agent_id().clone(),
            run.owner_id.clone().ok_or_else(|| AgentdError::Protocol("TaskFlow run lost owner id".to_string()))?,
            run.owner_epoch.ok_or_else(|| AgentdError::Protocol("TaskFlow run lost owner epoch".to_string()))?,
            run.generation.ok_or_else(|| AgentdError::Protocol("TaskFlow run lost generation".to_string()))?,
            run.fencing_token.clone().ok_or_else(|| AgentdError::Protocol("TaskFlow run lost fencing token".to_string()))?,
        )
        .map_err(|error| AgentdError::Protocol(format!("rebuild historical TaskFlow fence: {error}")))
    }

    fn terminal_receipt_from_ack(
        ack: &ProviderEffectAck,
        intent: &ProviderEffectIntent,
    ) -> Option<AuthorizedEffectProviderReceipt> {
        if ack.validate_for(intent).is_err() {
            return None;
        }
        let outcome = match ack.status {
            ProviderEffectAckStatus::Completed => codex_hepta_automation::AuthorizedEffectOutcome::Succeeded,
            ProviderEffectAckStatus::Rejected => codex_hepta_automation::AuthorizedEffectOutcome::Failed,
            ProviderEffectAckStatus::Accepted => return None,
        };
        let bytes = serde_json::to_vec(ack).ok()?;
        Some(AuthorizedEffectProviderReceipt {
            outcome,
            receipt_digest: Sha256Digest::for_bytes(&bytes),
        })
    }

    fn read_revocations_file(path: &Path) -> Result<FinalUseRevocations, AgentdError> {
        Ok(serde_json::from_slice(&read_protected_file(
            path,
            MAX_REVOCATIONS_FILE_BYTES,
            "automation effect revocations file",
        )?)?)
    }

    fn read_protected_file(path: &Path, max_bytes: u64, label: &str) -> Result<Vec<u8>, AgentdError> {
        if !path.is_absolute() {
            return Err(AgentdError::Invalid(format!("{label} must be absolute")));
        }
        let canonical = path.canonicalize()?;
        if canonical != path {
            return Err(AgentdError::Invalid(format!("{label} must be canonical and symlink-free")));
        }
        let metadata = fs::symlink_metadata(path)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() == 0 || metadata.len() > max_bytes {
            return Err(AgentdError::Invalid(format!("{label} is not a bounded regular file")));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if metadata.permissions().mode() & 0o077 != 0 {
                return Err(AgentdError::Invalid(format!("{label} must not be group/world accessible")));
            }
        }
        Ok(fs::read(path)?)
    }

    fn validate_host_identifier(label: &str, value: &str) -> Result<(), AgentdError> {
        if value.is_empty()
            || value.len() > 128
            || !value.bytes().all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
        {
            return Err(AgentdError::Invalid(format!("{label} must be a bounded identifier")));
        }
        Ok(())
    }

    fn decode_hex_array<const N: usize>(value: &str, label: &str) -> Result<[u8; N], AgentdError> {
        if value.len() != N * 2 {
            return Err(AgentdError::Invalid(format!("{label} must contain exactly {} hex characters", N * 2)));
        }
        let mut output = [0_u8; N];
        for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
            let high = hex_nibble(pair[0]).ok_or_else(|| AgentdError::Invalid(format!("{label} contains non-hex data")))?;
            let low = hex_nibble(pair[1]).ok_or_else(|| AgentdError::Invalid(format!("{label} contains non-hex data")))?;
            output[index] = (high << 4) | low;
        }
        Ok(output)
    }

    fn hex_nibble(value: u8) -> Option<u8> {
        match value {
            b'0'..=b'9' => Some(value - b'0'),
            b'a'..=b'f' => Some(value - b'a' + 10),
            b'A'..=b'F' => Some(value - b'A' + 10),
            _ => None,
        }
    }

    fn taskflow_error(error: codex_hepta_automation::TaskFlowError) -> AgentdError {
        AgentdError::Protocol(format!("automation TaskFlow product path: {error}"))
    }
    ''',
)

# Current technical documents: replace stale boundary claims and append the
# exact source slice without claiming deployment/acceptance.
for path in [
    "docs/modules/automation.taskflow/TECHNICAL.md",
    "qualification/module-execution-dossiers/detail/automation.taskflow.md",
]:
    text = read(path)
    text = text.replace("schema v16", "schema v22")
    text = text.replace("migrations `0004`-`0016`", "migrations `0004`-`0022`")
    text = text.replace(
        "Agentd has no independently provisioned `FinalUseAuthority` host configuration for TaskFlow effects",
        "Agentd has a named independently provisioned `FinalUseAuthority` effect host; selected-provider deployment and independent acceptance remain qualification gates",
    )
    text = text.replace(
        "no product caller currently binds it to the TaskFlow `AuthorizedEffectDriver` together with an independently provisioned `FinalUseAuthority` host",
        "the named Agentd product caller now binds durable preparation, an independently provisioned `FinalUseAuthority`, and the attested provider transport; target deployment and independent acceptance remain open",
    )
    if "Product effect and DecisionCell convergence (schema v22)" not in text:
        text += dedent(r'''

        ## Product effect and DecisionCell convergence (schema v22)

        The named Agentd control path now prepares a normal product effect before dispatch:
        it creates/reuses the existing TaskFlow definition and run, claims the exact step,
        freezes provider profile/key and historical fence, and only then consumes a signed
        final-use grant through the async provider adapter. A crash before a durable provider
        attempt can create only the next physical attempt after append-only no-contact
        recovery; a durable attempt is reconciliation-only. Provider configuration rotation
        must retain the exact old profile in the bounded recovery set, so restart lookup does
        not reinterpret an old operation through a new endpoint.

        `ThresholdCircuitCandidateV1` is the first real DecisionCell slice. Its immutable
        threshold and parameter digest are loaded from the automation owner, its allow/deny
        route is computed from the actual invocation, and the exact choice is persisted
        create-only before the caller observes it. Restart replays the recorded choice;
        successor parameters use exact predecessor/version binding and affect only new runs.
        This is a minimal cell, not a claim that general joins, feedback or subcircuits are
        implemented.

        Source implementation and exact-head tests do not assert selected-host deployment,
        provider credentials, independent acceptance, activation, promotion or release.
        ''')
    (ROOT / path).write_text(text)

# Focused CI includes the actual product and DecisionCell slices.
workflow = ".github/workflows/automation-taskflow-focused.yml"
if (ROOT / workflow).exists():
    text = read(workflow)
    if "Test product effect preparation" not in text:
        anchor = "      - name: Test automation package\n        run: cargo test -p codex-hepta-automation\n"
        addition = (
            "      - name: Test product effect preparation\n"
            "        run: cargo test -p codex-hepta-automation --test product_effect\n"
            "      - name: Test threshold DecisionCell\n"
            "        run: cargo test -p codex-hepta-automation --test threshold_circuit\n"
        )
        if anchor not in text:
            raise SystemExit(f"{workflow}: focused test anchor drifted")
        text = text.replace(anchor, addition + anchor, 1)
        (ROOT / workflow).write_text(text)

# Remove the one-shot relay recovery workflow from the final tree.
relay = ROOT / ".github/workflows/remote-desktop-recover.yml"
if relay.exists():
    relay.unlink()

print(json.dumps({"status": "APPLIED_AUTOMATION_TASKFLOW_CONVERGENCE", "schema": 22}, sort_keys=True))
