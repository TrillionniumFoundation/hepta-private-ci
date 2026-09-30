#!/usr/bin/env python3
"""One-shot, idempotent materialization for the reviewed AuthBus boundary patch."""

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 1:
        target.write_text(text.replace(old, new), encoding="utf-8")
        return
    if old_count == 0 and new_count == 1:
        return
    raise SystemExit(
        f"expected one old or one applied replacement in {path}; "
        f"old={old_count} new={new_count}"
    )


def replace_count(path: str, old: str, new: str, count: int) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == count:
        target.write_text(text.replace(old, new), encoding="utf-8")
        return
    if old_count == 0 and new_count == count:
        return
    raise SystemExit(
        f"expected {count} old or applied replacements in {path}; "
        f"old={old_count} new={new_count}"
    )


replace_once(
    "codex-rs/hepta-authbus/src/host.rs",
    "    pub async fn bootstrap(\n",
    "    pub(crate) async fn bootstrap(\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/bin/hepta-authbus-admin.rs",
    "use codex_hepta_authbus::AuthBusAuthorityHost;\n",
    "use codex_hepta_authbus::AuthBusAuthorityHost;\nuse codex_hepta_authbus::bootstrap_retryable;\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/bin/hepta-authbus-admin.rs",
    "    let host = AuthBusAuthorityHost::bootstrap(\n",
    "    let host = bootstrap_retryable(\n",
)

replace_once(
    "codex-rs/hepta-evidence/src/schema_validation.rs",
    "#[path = \"authbus_recovery_schema.rs\"]\nmod authbus_recovery_schema;\n",
    "#[path = \"authbus_recovery_schema.rs\"]\nmod authbus_recovery_schema;\n#[path = \"authbus_time_schema.rs\"]\nmod authbus_time_schema;\n",
)
replace_once(
    "codex-rs/hepta-evidence/src/schema_validation.rs",
    "        .chain(authbus_recovery_schema::REQUIRED_SCHEMA_OBJECTS)\n",
    "        .chain(authbus_recovery_schema::REQUIRED_SCHEMA_OBJECTS)\n        .chain(authbus_time_schema::REQUIRED_SCHEMA_OBJECTS)\n",
)
replace_once(
    "codex-rs/hepta-evidence/src/authbus_store.rs",
    "use crate::schema_validation::classify_sqlx_error;\nuse crate::store::now_millis;\n",
    "use crate::authbus_time::authbus_now;\nuse crate::schema_validation::classify_sqlx_error;\n",
)
replace_once(
    "codex-rs/hepta-evidence/src/authbus_store.rs",
    "        let now = u64::try_from(now_millis()?)\n",
    "        let now = u64::try_from(authbus_now(&mut transaction).await?)\n",
)
replace_once(
    "codex-rs/hepta-evidence/src/authbus_outbox.rs",
    "use crate::schema_validation::classify_sqlx_error;\nuse crate::store::now_millis;\n",
    "use crate::authbus_time::authbus_now;\nuse crate::schema_validation::classify_sqlx_error;\n",
)
replace_count(
    "codex-rs/hepta-evidence/src/authbus_outbox.rs",
    "let now = now_millis()?;",
    "let now = authbus_now(&mut tx).await?;",
    3,
)
replace_once(
    "codex-rs/hepta-evidence/src/authbus_outbox_worker.rs",
    "use crate::schema_validation::classify_sqlx_error;\nuse crate::store::now_millis;\n",
    "use crate::authbus_time::authbus_now;\nuse crate::schema_validation::classify_sqlx_error;\n",
)
replace_once(
    "codex-rs/hepta-evidence/src/authbus_outbox_worker.rs",
    "    let now = now_millis()?;\n",
    "    let now = authbus_now(&mut tx).await?;\n",
)
replace_once(
    "codex-rs/hepta-evidence/src/authbus_recovery.rs",
    "use crate::schema_validation::classify_sqlx_error;\nuse crate::store::now_millis;\n",
    "use crate::authbus_time::authbus_now;\nuse crate::schema_validation::classify_sqlx_error;\n",
)
replace_count(
    "codex-rs/hepta-evidence/src/authbus_recovery.rs",
    ".bind(now_millis()?)",
    ".bind(authbus_now(&mut tx).await?)",
    4,
)
replace_once(
    "codex-rs/hepta-evidence/src/authbus_operations.rs",
    "use crate::schema_validation::classify_sqlx_error;\nuse crate::store::now_millis;\n",
    "use crate::schema_validation::classify_sqlx_error;\n",
)
replace_once(
    "codex-rs/hepta-evidence/src/authbus_operations.rs",
    "        let observed_at_ms = now_millis()?;\n",
    "        let observed_at_ms = i64::try_from(self.authbus_monotonic_now_ms().await?)\n            .map_err(|_| EvidenceError::Unavailable(\"AuthBus time floor exceeds i64\".into()))?;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/authbus_ingress.rs",
    "    let now = now_ms()?;\n    if request.expires_at_ms <= now",
    "    let now = host\n        .evidence\n        .authbus_monotonic_now_ms()\n        .await\n        .map_err(|error| invalid(&error.to_string()))?;\n    if request.expires_at_ms <= now",
)
replace_once(
    "codex-rs/hepta-agentd/src/authbus_ingress.rs",
    "            now_ms()?,\n        )\n        .map_err(|error| invalid(&error.to_string()))?;\n",
    "            host.evidence\n                .authbus_monotonic_now_ms()\n                .await\n                .map_err(|error| invalid(&error.to_string()))?,\n        )\n        .map_err(|error| invalid(&error.to_string()))?;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/authbus_dispatch.rs",
    "use crate::authbus_ingress::now_ms;\n",
    "",
)
replace_count(
    "codex-rs/hepta-agentd/src/authbus_dispatch.rs",
    "            now_ms()?,\n",
    "            host.evidence\n                .authbus_monotonic_now_ms()\n                .await\n                .map_err(|error| invalid(&error.to_string()))?,\n",
    2,
)
