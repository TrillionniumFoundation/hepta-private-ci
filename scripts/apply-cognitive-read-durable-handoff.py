#!/usr/bin/env python3
"""Apply the durable cognitive read-request handoff to the existing owners.

This is an ordinary source-authoring transformation. It neither runs
qualification nor changes activation, acceptance, or release state.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

CLIENT = ROOT / "codex-rs/hepta-agentd/src/client.rs"
AGENTD_LIB = ROOT / "codex-rs/hepta-agentd/src/lib.rs"
NATIVE_APP = ROOT / "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
NATIVE_RUN = ROOT / "codex-rs/hepta-infer-worker-host/src/native_run_control.rs"
NATIVE_CONTROL = ROOT / "codex-rs/hepta-infer-core/src/native_control.rs"
DELIVERY = ROOT / "codex-rs/hepta-infer-core/src/cognitive_delivery.rs"
DELIVERY_TESTS = ROOT / "codex-rs/hepta-infer-core/src/cognitive_delivery_tests.rs"
NATIVE_CONTROL_TESTS = ROOT / "codex-rs/hepta-infer-core/src/native_control_tests.rs"
NATIVE_RUN_TESTS = ROOT / "codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs"
JOIN_TESTS = ROOT / "codex-rs/hepta-agentd/src/cognitive_retrieval_delivery_tests.rs"


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args], cwd=ROOT, text=True
    ).strip()


def replace_once(path: Path, old: str, new: str) -> None:
    body = path.read_text()
    if old not in body and body.count(new) == 1:
        return
    if body.count(old) != 1:
        raise ValueError(f"source shape drift: {path.relative_to(ROOT)}")
    path.write_text(body.replace(old, new, 1))


def add_dispatch_literal_field(path: Path) -> None:
    body = path.read_text()
    pattern = re.compile(
        r"(?m)^([ \t]*)(?!pub )owner_context_digest: ([^\n]+),\n"
        r"([ \t]*)codex_payload_digest:"
    )

    def replacement(match: re.Match[str]) -> str:
        left, value, right = match.groups()
        if left != right:
            raise ValueError(f"dispatch field indentation drift: {path.relative_to(ROOT)}")
        return (
            f"{left}owner_context_digest: {value},\n"
            f"{left}cognitive_read_request_id: None,\n"
            f"{left}codex_payload_digest:"
        )

    next_body, count = pattern.subn(replacement, body)
    if count == 0:
        if "cognitive_read_request_id:" not in body:
            raise ValueError(f"missing NativeDispatch literal: {path.relative_to(ROOT)}")
        return
    path.write_text(next_body)


def prepare_client() -> None:
    replace_once(
        CLIENT,
        """pub struct AgentdClient {
    socket_path: PathBuf,
    expected_agent_id: AgentId,
    spawn_generation: u64,
    next_request_id: AtomicU64,
    timeout: Duration,
}

impl AgentdClient {
""",
        """pub struct AgentdClient {
    socket_path: PathBuf,
    expected_agent_id: AgentId,
    spawn_generation: u64,
    next_request_id: AtomicU64,
    timeout: Duration,
}

/// Request-local identity for one context preparation produced by Agentd.
///
/// This local Rust value is not serialized on the control protocol and grants
/// no authority. It preserves the already authenticated request ID so the
/// existing native journal can bind a physical attempt to the exact learning
/// preparation without matching on a context digest alone.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveContextPreparation {
    request_id: u64,
    snapshot: crate::CognitiveContextSnapshot,
}

impl CognitiveContextPreparation {
    #[must_use]
    pub const fn request_id(&self) -> u64 {
        self.request_id
    }

    #[must_use]
    pub const fn snapshot(&self) -> &crate::CognitiveContextSnapshot {
        &self.snapshot
    }

    #[must_use]
    pub fn into_snapshot(self) -> crate::CognitiveContextSnapshot {
        self.snapshot
    }
}

impl AgentdClient {
""",
    )
    replace_once(
        CLIENT,
        """    /// Read verified context through this exact generation's canonical owner.
    pub async fn cognitive_context(
        &self,
        query: String,
        limit: u16,
    ) -> Result<crate::CognitiveContextSnapshot, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::CognitiveContext { query, limit },
            })
            .await?
            .payload
        {
            AgentdPayload::CognitiveContext(snapshot) => Ok(snapshot),
            payload => unexpected(payload),
        }
    }
""",
        """    /// Read verified context through this exact generation's canonical owner.
    ///
    /// Compatibility callers receive only the snapshot. Product code that
    /// needs to join the preparation to a physical native attempt must use
    /// [`Self::cognitive_context_prepared`] and persist its request identity.
    pub async fn cognitive_context(
        &self,
        query: String,
        limit: u16,
    ) -> Result<crate::CognitiveContextSnapshot, AgentdError> {
        Ok(self
            .cognitive_context_prepared(query, limit)
            .await?
            .into_snapshot())
    }

    /// Read verified context and retain the exact authenticated control request.
    ///
    /// The response identity is already checked by [`Self::send`]. The wrapper
    /// is request-local evidence only; it is not a freshness lease, delivery
    /// acknowledgement, or training grant.
    pub async fn cognitive_context_prepared(
        &self,
        query: String,
        limit: u16,
    ) -> Result<CognitiveContextPreparation, AgentdError> {
        let request_id = self.request_id();
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id,
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::CognitiveContext { query, limit },
            })
            .await?;
        match response.payload {
            AgentdPayload::CognitiveContext(snapshot) => Ok(CognitiveContextPreparation {
                request_id: response.request_id,
                snapshot,
            }),
            payload => unexpected(payload),
        }
    }
""",
    )
    replace_once(
        AGENTD_LIB,
        "pub use client::AgentdClient;\n",
        "pub use client::AgentdClient;\npub use client::CognitiveContextPreparation;\n",
    )


def prepare_native_dispatch() -> None:
    replace_once(
        NATIVE_CONTROL,
        """    #[serde(default)]
    pub owner_context_digest: Option<String>,
    /// Exact serialized turn/start payload digest. Optional only for replaying
""",
        """    #[serde(default)]
    pub owner_context_digest: Option<String>,
    /// Exact authenticated Agentd read request that produced the owner context.
    ///
    /// Historical rows may omit this field and remain replayable, but they
    /// cannot satisfy a modern preparation-to-delivery join.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cognitive_read_request_id: Option<u64>,
    /// Exact serialized turn/start payload digest. Optional only for replaying
""",
    )
    replace_once(
        NATIVE_CONTROL,
        """                if let Some(owner_context_digest) = &dispatch.owner_context_digest {
                    validate_digest(owner_context_digest, "native owner context")?;
                }
                let codex_fields = [
""",
        """                if let Some(owner_context_digest) = &dispatch.owner_context_digest {
                    validate_digest(owner_context_digest, "native owner context")?;
                }
                if dispatch.cognitive_read_request_id == Some(0)
                    || (dispatch.cognitive_read_request_id.is_some()
                        && dispatch.owner_context_digest.is_none())
                {
                    return Err(Error::InvalidIdentity(
                        "native cognitive read request binding",
                    ));
                }
                let codex_fields = [
""",
    )
    replace_once(
        NATIVE_APP,
        """            owner_context_digest,
            codex_payload_digest:""",
        """            owner_context_digest,
            cognitive_read_request_id: None,
            codex_payload_digest:""",
    )
    for path in (
        NATIVE_APP,
        NATIVE_CONTROL_TESTS,
        NATIVE_RUN_TESTS,
        DELIVERY_TESTS,
        JOIN_TESTS,
    ):
        add_dispatch_literal_field(path)
    replace_once(
        NATIVE_APP,
        "            cognitive_read_request_id: None,\n",
        """            cognitive_read_request_id: context
                .as_ref()
                .map(CognitiveContextPreparation::request_id),
""",
    )
    replace_once(
        DELIVERY_TESTS,
        "        cognitive_read_request_id: None,\n",
        "        cognitive_read_request_id: Some(17),\n",
    )
    replace_once(
        JOIN_TESTS,
        "        cognitive_read_request_id: None,\n",
        "        cognitive_read_request_id: Some(read_request_id),\n",
    )


def prepare_worker() -> None:
    replace_once(
        NATIVE_APP,
        "use codex_hepta_agentd::COGNITIVE_CONTEXT_REVALIDATION_CAPABILITY;\n",
        """use codex_hepta_agentd::COGNITIVE_CONTEXT_REVALIDATION_CAPABILITY;
use codex_hepta_agentd::CognitiveContextPreparation;
""",
    )
    replace_once(
        NATIVE_APP,
        """        let context = match context_query {
            Some(query) => Some(owner.cognitive_context(query, /*limit*/ 4).await?),
            None => None,
        };
        let owner_context_digest = context
            .as_ref()
            .map(|snapshot| -> Result<_> { Ok(control::digest(&serde_json::to_vec(snapshot)?)) })
            .transpose()?;
        let additional_context = context
            .as_ref()
            .map(|snapshot| -> Result<_> {
                let value = serde_json::to_string(&snapshot)?;
""",
        """        let context = match context_query {
            Some(query) => Some(
                owner
                    .cognitive_context_prepared(query, /*limit*/ 4)
                    .await?,
            ),
            None => None,
        };
        let owner_context_digest = context
            .as_ref()
            .map(|context| -> Result<_> {
                Ok(control::digest(&serde_json::to_vec(context.snapshot())?))
            })
            .transpose()?;
        let additional_context = context
            .as_ref()
            .map(|context| -> Result<_> {
                let value = serde_json::to_string(context.snapshot())?;
""",
    )
    replace_once(
        NATIVE_APP,
        """        if let Some(snapshot) = context.as_ref() {
            let revalidated = match owner.revalidate_cognitive_context(snapshot).await {
""",
        """        if let Some(context) = context.as_ref() {
            let snapshot = context.snapshot();
            let revalidated = match owner.revalidate_cognitive_context(snapshot).await {
""",
    )
    replace_once(
        NATIVE_APP,
        """            &authority_witness,
            &app_server_version,
        )?;
""",
        """            &authority_witness,
            &app_server_version,
            context
                .as_ref()
                .map(CognitiveContextPreparation::request_id),
        )?;
""",
    )
    replace_once(
        NATIVE_APP,
        """    authority_witness: &str,
    app_server_version: &str,
) -> Result<()> {
""",
        """    authority_witness: &str,
    app_server_version: &str,
    cognitive_read_request_id: Option<u64>,
) -> Result<()> {
""",
    )
    replace_once(
        NATIVE_APP,
        """        && dispatch.app_server_version.as_deref() == Some(app_server_version)
        && dispatch.protocol_id.as_deref() == Some(APP_SERVER_V2_PROTOCOL_ID);
""",
        """        && dispatch.app_server_version.as_deref() == Some(app_server_version)
        && dispatch.protocol_id.as_deref() == Some(APP_SERVER_V2_PROTOCOL_ID)
        && dispatch.cognitive_read_request_id == cognitive_read_request_id;
""",
    )


def prepare_delivery_view() -> None:
    replace_once(
        DELIVERY,
        """    pub fn context_digest(&self) -> Digest32 {
        self.context_digest
    }

    pub fn journal_revision(&self) -> u64 {
""",
        """    pub fn context_digest(&self) -> Digest32 {
        self.context_digest
    }

    /// Exact Agentd read request persisted by the normal native product path.
    ///
    /// None identifies historical dispatches that predate the additive field;
    /// it must not be reconstructed from a context digest.
    pub fn cognitive_read_request_id(&self) -> Option<u64> {
        self.record
            .dispatch
            .as_ref()
            .and_then(|dispatch| dispatch.cognitive_read_request_id)
    }

    pub fn journal_revision(&self) -> u64 {
""",
    )
    replace_once(
        DELIVERY,
        """        Ok(Some(CognitiveContextDeliveryV1 {
            record,
            context_digest,
            state,
            binding_digest: Digest32::of_bytes(&bytes),
        }))
    }
}

fn required_digest""",
        """        Ok(Some(CognitiveContextDeliveryV1 {
            record,
            context_digest,
            state,
            binding_digest: Digest32::of_bytes(&bytes),
        }))
    }

    /// Join the exact persisted Agentd preparation identity to native evidence.
    ///
    /// Historical dispatches without the request identity fail closed rather
    /// than falling back to content-digest matching.
    pub fn cognitive_context_delivery_for_read(
        &self,
        expected_request: &NativeRequest,
        expected_context_digest: Digest32,
        expected_read_request_id: u64,
    ) -> Result<Option<CognitiveContextDeliveryV1<'_>>, CognitiveContextDeliveryError> {
        if expected_read_request_id == 0 {
            return Err(CognitiveContextDeliveryError::ReadRequestMismatch);
        }
        let evidence =
            self.cognitive_context_delivery(expected_request, expected_context_digest)?;
        let Some(evidence) = evidence else {
            return Ok(None);
        };
        if evidence.cognitive_read_request_id() != Some(expected_read_request_id) {
            return Err(CognitiveContextDeliveryError::ReadRequestMismatch);
        }
        Ok(Some(evidence))
    }
}

fn required_digest""",
    )
    replace_once(
        DELIVERY,
        """    ContextMismatch,
    IncompleteDispatch,
""",
        """    ContextMismatch,
    ReadRequestMismatch,
    IncompleteDispatch,
""",
    )
    replace_once(
        NATIVE_RUN,
        ".cognitive_context_delivery(expected_request, expected_context_digest)\n",
        """.cognitive_context_delivery_for_read(
                            expected_request,
                            expected_context_digest,
                            read_request_id,
                        )
""",
    )
    replace_once(
        NATIVE_RUN,
        """            .map_err(Into::into)
    }

    /// Reserves before any provider call, journals dispatch before `turn/start`,
""",
        """            .map_err(Into::into)
    }

    /// Correlate using the read request identity durably carried by the normal
    /// Agentd-to-native product handoff.
    ///
    /// The caller still independently pins the complete native request and
    /// context digest. Missing historical identities fail closed.
    pub fn inspect_persisted_cognitive_assignment(
        &self,
        control: &DurableInferenceControl,
        learning: &codex_hepta_agentd::CognitiveRetrievalLearningSink,
        expected_request: &NativeRequest,
        expected_context_digest: codex_hepta_types::Digest32,
    ) -> Result<(
        codex_hepta_infer_core::CognitiveContextDeliveryStateV1,
        codex_hepta_types::Digest32,
    )> {
        let evidence = control
            .cognitive_context_delivery(expected_request, expected_context_digest)
            .map_err(|error| error.to_string())?
            .ok_or("no context-bound native dispatch was observed")?;
        let read_request_id = evidence
            .cognitive_read_request_id()
            .ok_or("native dispatch predates durable cognitive read identity")?;
        self.inspect_cognitive_assignment(
            control,
            learning,
            expected_request,
            read_request_id,
            expected_context_digest,
        )
    }

    /// Reserves before any provider call, journals dispatch before `turn/start`,
""",
    )


def prepare_tests() -> None:
    replace_once(
        DELIVERY_TESTS,
        """    owner.dispatch_native("request-1", dispatch()).unwrap();
    let mut substitutions = Vec::new();
""",
        """    owner.dispatch_native("request-1", dispatch()).unwrap();
    let exact = owner
        .cognitive_context_delivery_for_read(&request(), context_digest(), 17)
        .unwrap()
        .unwrap();
    assert_eq!(exact.cognitive_read_request_id(), Some(17));
    assert_eq!(
        owner
            .cognitive_context_delivery_for_read(&request(), context_digest(), 18)
            .unwrap_err(),
        CognitiveContextDeliveryError::ReadRequestMismatch
    );
    let mut substitutions = Vec::new();
""",
    )
    replace_once(
        JOIN_TESTS,
        """    assert_eq!(accepted.0, CognitiveContextDeliveryStateV1::TurnAccepted);
    assert_ne!(pending.1, accepted.1);
""",
        """    assert_eq!(accepted.0, CognitiveContextDeliveryStateV1::TurnAccepted);
    assert_ne!(pending.1, accepted.1);
    assert_eq!(
        driver
            .inspect_persisted_cognitive_assignment(&control, &sink, &request, context)
            .unwrap(),
        accepted
    );
""",
    )
    replace_once(
        JOIN_TESTS,
        """        driver
            .inspect_cognitive_assignment(&reopened, &sink, &request, read_request_id, context)
            .unwrap(),
        accepted
    );
""",
        """        driver
            .inspect_persisted_cognitive_assignment(&reopened, &sink, &request, context)
            .unwrap(),
        accepted
    );
""",
    )


def verify_shape() -> None:
    for path in (
        CLIENT,
        AGENTD_LIB,
        NATIVE_APP,
        NATIVE_RUN,
        NATIVE_CONTROL,
        DELIVERY,
        DELIVERY_TESTS,
        JOIN_TESTS,
    ):
        if not path.is_file():
            raise ValueError(f"missing authored source: {path.relative_to(ROOT)}")
    if NATIVE_APP.read_text().count("cognitive_read_request_id: context") != 1:
        raise ValueError("normal native dispatch does not carry exactly one read request identity")
    if CLIENT.read_text().count("pub async fn cognitive_context_prepared(") != 1:
        raise ValueError("prepared Agentd client surface is not unique")
    if NATIVE_CONTROL.read_text().count("pub cognitive_read_request_id: Option<u64>") != 1:
        raise ValueError("native journal read request field is not unique")
    if JOIN_TESTS.read_text().count("inspect_persisted_cognitive_assignment") < 2:
        raise ValueError("delivery integration test does not exercise persisted identity")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        raise ValueError("expected SHA must be lowercase hexadecimal")
    if git("rev-parse", "HEAD") != args.expected_sha:
        raise ValueError("durable handoff authoring requires the exact checked-out head")
    prepare_client()
    prepare_native_dispatch()
    prepare_worker()
    prepare_delivery_view()
    prepare_tests()
    verify_shape()


if __name__ == "__main__":
    main()
