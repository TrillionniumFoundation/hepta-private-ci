#!/usr/bin/env python3
"""Apply and verify the inference.control unique-writer actor migration.

The migration uses exact structural anchors and is idempotent. A missing or
ambiguous anchor fails closed instead of applying a broad source rewrite.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTOR = ROOT / "codex-rs/hepta-infer-worker-host/src/control_actor.rs"
LIB = ROOT / "codex-rs/hepta-infer-worker-host/src/lib.rs"
RUN_CONTROL = ROOT / "codex-rs/hepta-infer-worker-host/src/native_run_control.rs"
APP_SERVER = ROOT / "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
WORKER_CLI = ROOT / "codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one exact anchor, found {count}")
    return text.replace(old, new, 1)


def write_if_changed(path: Path, text: str) -> bool:
    original = path.read_text(encoding="utf-8")
    if original == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def migrate_actor(text: str) -> str:
    if "pub async fn prepare_dispatch_raw" in text:
        return text
    text = replace_once(
        text,
        "use codex_hepta_infer_core::durable_control::native::NativeDispatch;\n",
        "use codex_hepta_infer_core::durable_control::native::NativeDispatch;\n"
        "use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;\n",
        "actor rejection import",
    )
    text = replace_once(
        text,
        "    pub async fn prepare_dispatch(\n",
        "    pub async fn prepare_dispatch_raw(\n"
        "        &self,\n"
        "        request_id: String,\n"
        "        dispatch: NativeDispatch,\n"
        "    ) -> ActorResult<(NativeRunRecord, NativePreEffectAbortToken)> {\n"
        "        let (reply, response) = oneshot::channel();\n"
        "        self.send(Command::PrepareDispatch {\n"
        "            request_id,\n"
        "            dispatch,\n"
        "            reply,\n"
        "        })?;\n"
        "        receive(response).await\n"
        "    }\n\n"
        "    pub async fn prepare_authorized_dispatch_raw(\n"
        "        &self,\n"
        "        request_id: String,\n"
        "        dispatch: NativeDispatch,\n"
        "        plan: Arc<VerifiedExecutionPlan>,\n"
        "        now_unix_ms: u64,\n"
        "    ) -> ActorResult<(NativeRunRecord, NativePreEffectAbortToken)> {\n"
        "        let (reply, response) = oneshot::channel();\n"
        "        self.send(Command::PrepareAuthorizedDispatch {\n"
        "            request_id,\n"
        "            dispatch,\n"
        "            plan,\n"
        "            now_unix_ms,\n"
        "            reply,\n"
        "        })?;\n"
        "        receive(response).await\n"
        "    }\n\n"
        "    pub async fn prepare_dispatch(\n",
        "actor raw dispatch methods",
    )
    text = replace_once(
        text,
        "    pub async fn started(\n",
        "    pub async fn abort_raw(\n"
        "        &self,\n"
        "        token: NativePreEffectAbortToken,\n"
        "        reason: String,\n"
        "    ) -> ActorResult<NativeRunRecord> {\n"
        "        let (reply, response) = oneshot::channel();\n"
        "        self.send(Command::AbortBeforeEffect {\n"
        "            token,\n"
        "            reason,\n"
        "            reply,\n"
        "        })?;\n"
        "        receive(response).await\n"
        "    }\n\n"
        "    pub async fn started(\n",
        "actor raw abort method",
    )
    text = replace_once(
        text,
        "    pub async fn cancel(&self, request_id: String) -> ActorResult<NativeRunRecord> {\n",
        "    pub async fn reject_before_start(\n"
        "        &self,\n"
        "        request_id: String,\n"
        "        rejection: NativeDispatchRejection,\n"
        "    ) -> ActorResult<NativeRunRecord> {\n"
        "        let (reply, response) = oneshot::channel();\n"
        "        self.send(Command::RejectBeforeStart {\n"
        "            request_id,\n"
        "            rejection,\n"
        "            reply,\n"
        "        })?;\n"
        "        receive(response).await\n"
        "    }\n\n"
        "    pub async fn cancel(&self, request_id: String) -> ActorResult<NativeRunRecord> {\n",
        "actor rejection method",
    )
    text = replace_once(
        text,
        "    pub async fn settle_authorized(\n",
        "    pub async fn settle_legacy(\n"
        "        &self,\n"
        "        request_id: String,\n"
        "        output: NativeRunOutput,\n"
        "    ) -> ActorResult<NativeRunRecord> {\n"
        "        let (reply, response) = oneshot::channel();\n"
        "        self.send(Command::SettleLegacy {\n"
        "            request_id,\n"
        "            output,\n"
        "            reply,\n"
        "        })?;\n"
        "        receive(response).await\n"
        "    }\n\n"
        "    pub async fn settle_authorized(\n",
        "actor legacy settlement method",
    )
    text = replace_once(
        text,
        "    SettleAuthorized {\n",
        "    RejectBeforeStart {\n"
        "        request_id: String,\n"
        "        rejection: NativeDispatchRejection,\n"
        "        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,\n"
        "    },\n"
        "    SettleLegacy {\n"
        "        request_id: String,\n"
        "        output: NativeRunOutput,\n"
        "        reply: oneshot::Sender<ActorResult<NativeRunRecord>>,\n"
        "    },\n"
        "    SettleAuthorized {\n",
        "actor command variants",
    )
    text = replace_once(
        text,
        "            Self::SettleAuthorized {\n",
        "            Self::RejectBeforeStart {\n"
        "                request_id,\n"
        "                rejection,\n"
        "                reply,\n"
        "            } => send_result(\n"
        "                reply,\n"
        "                control.reject_native_before_start(&request_id, rejection),\n"
        "            ),\n"
        "            Self::SettleLegacy {\n"
        "                request_id,\n"
        "                output,\n"
        "                reply,\n"
        "            } => send_result(reply, control.settle_native(&request_id, output)),\n"
        "            Self::SettleAuthorized {\n",
        "actor command handlers",
    )
    return text


def migrate_lib(text: str) -> str:
    if "pub mod control_port;" not in text:
        text = replace_once(
            text,
            "pub mod control_actor;\n",
            "pub mod control_actor;\npub mod control_port;\n",
            "library control port module",
        )
    if "pub use control_port::NativeControlPort;" not in text:
        text = replace_once(
            text,
            "pub use control_actor::PreparedNativeEffect;\n",
            "pub use control_actor::PreparedNativeEffect;\n"
            "pub use control_port::NativeControlPort;\n",
            "library control port export",
        )
    return text


def migrate_driver(path: Path, text: str) -> str:
    if "&mut dyn NativeControlPort" in text:
        return text
    text = replace_once(
        text,
        "use codex_hepta_infer_core::durable_control::DurableInferenceControl;\n",
        "use crate::control_port::NativeControlPort;\n",
        f"{path.name} control import",
    )
    count = text.count("&mut DurableInferenceControl")
    if count == 0:
        raise ValueError(f"{path.name}: no direct writer parameters found")
    return text.replace("&mut DurableInferenceControl", "&mut dyn NativeControlPort")


def migrate_cli(text: str) -> str:
    if "NativeJournalWriterActor::spawn" in text:
        return text
    text = replace_once(
        text,
        "use codex_hepta_infer_core::durable_control::DurableInferenceControl;\n",
        "",
        "worker CLI direct writer import",
    )
    text = replace_once(
        text,
        "use codex_hepta_infer_worker_host::NativeOutputProtector;\n",
        "use codex_hepta_infer_worker_host::NativeJournalWriterActor;\n"
        "use codex_hepta_infer_worker_host::NativeOutputProtector;\n",
        "worker CLI actor import",
    )
    text = replace_once(
        text,
        "    let mut control = DurableInferenceControl::open(journal, /*capacity*/ 16_384)?;\n",
        "    let actor = NativeJournalWriterActor::spawn(journal, 16_384)?;\n"
        "    let mut control = actor.handle();\n",
        "worker CLI actor spawn",
    )
    text = replace_once(
        text,
        "    signal_task.abort();\n    let output = result?;\n",
        "    signal_task.abort();\n"
        "    let shutdown_result = actor.shutdown().await;\n"
        "    let output = result?;\n"
        "    shutdown_result?;\n",
        "worker CLI actor shutdown",
    )
    return text


def apply() -> None:
    changes: list[str] = []
    migrations = (
        (ACTOR, migrate_actor),
        (LIB, migrate_lib),
        (RUN_CONTROL, lambda value: migrate_driver(RUN_CONTROL, value)),
        (APP_SERVER, lambda value: migrate_driver(APP_SERVER, value)),
        (WORKER_CLI, migrate_cli),
    )
    for path, migration in migrations:
        original = path.read_text(encoding="utf-8")
        migrated = migration(original)
        if write_if_changed(path, migrated):
            changes.append(str(path.relative_to(ROOT)))
    print({"changed": changes})


def check() -> None:
    failures: list[str] = []
    for path in (RUN_CONTROL, APP_SERVER):
        text = path.read_text(encoding="utf-8")
        if "&mut DurableInferenceControl" in text or "&mut dyn NativeControlPort" not in text:
            failures.append(f"{path.relative_to(ROOT)} is not actor-port migrated")
    actor_text = ACTOR.read_text(encoding="utf-8")
    for marker in (
        "prepare_dispatch_raw",
        "prepare_authorized_dispatch_raw",
        "abort_raw",
        "reject_before_start",
        "settle_legacy",
    ):
        if marker not in actor_text:
            failures.append(f"control actor missing {marker}")
    cli_text = WORKER_CLI.read_text(encoding="utf-8")
    if "NativeJournalWriterActor::spawn" not in cli_text:
        failures.append("production worker CLI does not use the journal-writer actor")
    if failures:
        raise SystemExit("\n".join(failures))
    print("inference.control actor migration is current")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("apply", "check"))
    args = parser.parse_args()
    try:
        if args.command == "apply":
            apply()
        else:
            check()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
