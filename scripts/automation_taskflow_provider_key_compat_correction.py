#!/usr/bin/env python3
"""Tighten the one-shot provider-key repair to preserve conflict semantics."""

from pathlib import Path


def replace_once(relative: str, old: str, new: str) -> None:
    path = Path(relative)
    body = path.read_text(encoding="utf-8")
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected one correction anchor, found {count}")
    path.write_text(body.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    host = "codex-rs/hepta-agentd/src/automation_effect_host.rs"
    replace_once(
        host,
        """    async fn lookup(
        &self,
        pending: &AuthorizedEffectPending,
    ) -> AuthorizedProviderEffectLookup {
        let Ok(provider_intent) = agentd_schema_v1_provider_intent(
            &self.provider_scope,
            &pending.run_id,
            &pending.step_id,
            &pending.payload_digest,
        ) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        let lookup = self
            .inner
            .adapter()
            .lookup_for_intent(&provider_intent)
            .await;
        agentd_schema_v1_provider_lookup(&provider_intent, lookup)
    }
""",
        """    async fn lookup(
        &self,
        pending: &AuthorizedEffectPending,
    ) -> Result<AuthorizedProviderEffectLookup, AgentdError> {
        let provider_intent = agentd_schema_v1_provider_intent(
            &self.provider_scope,
            &pending.run_id,
            &pending.step_id,
            &pending.payload_digest,
        )
        .map_err(|error| {
            AgentdError::Invalid(format!(\"derive schema-v1 provider effect key: {error:?}\"))
        })?;
        let lookup = self
            .inner
            .adapter()
            .lookup_for_intent(&provider_intent)
            .await;
        agentd_schema_v1_provider_lookup(&provider_intent, lookup)
    }
""",
    )
    replace_once(
        host,
        """fn agentd_schema_v1_provider_lookup(
    provider_intent: &ProviderEffectIntent,
    lookup: ProviderEffectLookup,
) -> AuthorizedProviderEffectLookup {
    match lookup {
        ProviderEffectLookup::Ack(ack) if ack.validate_for(provider_intent).is_ok() => {
            agentd_schema_v1_terminal_receipt(&ack).map_or(
                AuthorizedProviderEffectLookup::Unresolved,
                AuthorizedProviderEffectLookup::Observed,
            )
        }
        ProviderEffectLookup::Ack(_)
        | ProviderEffectLookup::NotFound
        | ProviderEffectLookup::Conflict { .. }
        | ProviderEffectLookup::Unknown => AuthorizedProviderEffectLookup::Unresolved,
    }
}
""",
        """fn agentd_schema_v1_provider_lookup(
    provider_intent: &ProviderEffectIntent,
    lookup: ProviderEffectLookup,
) -> Result<AuthorizedProviderEffectLookup, AgentdError> {
    match lookup {
        ProviderEffectLookup::Ack(ack) => {
            ack.validate_for(provider_intent).map_err(|_| {
                AgentdError::Protocol(
                    \"provider status acknowledgement mismatched the durable schema-v1 intent\"
                        .to_string(),
                )
            })?;
            Ok(agentd_schema_v1_terminal_receipt(&ack).map_or(
                AuthorizedProviderEffectLookup::Unresolved,
                AuthorizedProviderEffectLookup::Observed,
            ))
        }
        ProviderEffectLookup::NotFound | ProviderEffectLookup::Unknown => {
            Ok(AuthorizedProviderEffectLookup::Unresolved)
        }
        ProviderEffectLookup::Conflict { .. } => Err(AgentdError::Protocol(
            \"provider reports a same-key payload conflict\".to_string(),
        )),
    }
}
""",
    )
    replace_once(
        host,
        "match driver.lookup(&pending).await {",
        "match driver.lookup(&pending).await? {",
    )
    replace_once(
        host,
        """            agentd_schema_v1_provider_lookup(&provider_intent, ProviderEffectLookup::NotFound),
            AuthorizedProviderEffectLookup::Unresolved
""",
        """            agentd_schema_v1_provider_lookup(&provider_intent, ProviderEffectLookup::NotFound)
                .expect(\"NotFound remains quarantined\"),
            AuthorizedProviderEffectLookup::Unresolved
""",
    )
    replace_once(
        host,
        """            AuthorizedProviderEffectLookup::Unresolved
        );
    }

    #[tokio::test(flavor = \"multi_thread\", worker_threads = 2)]
""",
        """            AuthorizedProviderEffectLookup::Unresolved
        );
        assert!(agentd_schema_v1_provider_lookup(
            &provider_intent,
            ProviderEffectLookup::Conflict {
                observed_payload_sha256: Some(Sha256Digest::for_bytes(b\"different-payload\")),
            },
        )
        .is_err());
    }

    #[tokio::test(flavor = \"multi_thread\", worker_threads = 2)]
""",
    )

    technical = "docs/modules/automation.taskflow/TECHNICAL.md"
    replace_once(
        technical,
        """compatibility profile, provider `NotFound`, conflict and transport-unknown remain
unresolved quarantine; they are not promoted to absence proof. A different key
""",
        """compatibility profile, provider `NotFound` and transport-unknown remain
unresolved quarantine and are not promoted to absence proof; a same-key payload
conflict retains the existing fail-closed error. A different key
""",
    )

    runbook = "docs/modules/automation.taskflow/MIGRATION_V19_RUNBOOK.md"
    replace_once(
        runbook,
        """and already-pending effects. A v19 upgrade must query that same key; `NotFound`,
conflict or transport-unknown remains unresolved and cannot prove absence. A
future key profile requires a new host schema plus a durable profile/key field
""",
        """and already-pending effects. A v19 upgrade must query that same key; `NotFound`
and transport-unknown remain unresolved and cannot prove absence, while a
same-key payload conflict keeps the pre-existing fail-closed error. A future key
profile requires a new host schema plus a durable profile/key field
""",
    )

    dossier = "qualification/module-execution-dossiers/detail/automation.taskflow.md"
    replace_once(
        dossier,
        """`for_operation(provider_scope, run_id, step_id)` provider key. Status `NotFound`
under this compatibility profile remains unresolved, so an upgrade cannot query
a different key and manufacture safe retry. Independent issuer/provider
""",
        """`for_operation(provider_scope, run_id, step_id)` provider key. Status `NotFound`
and transport-unknown under this compatibility profile remain unresolved, while
a same-key payload conflict remains fail-closed; an upgrade therefore cannot
query a different key and manufacture safe retry. Independent issuer/provider
""",
    )


if __name__ == "__main__":
    main()
