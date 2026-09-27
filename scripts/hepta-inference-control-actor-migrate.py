#!/usr/bin/env python3
"""Verify the completed inference.control unique-writer actor migration.

The former source-rewrite helper was intentionally retired after migration.
Future changes are checked against explicit product invariants instead of
silently rewriting Rust with stale textual anchors.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "codex-rs/hepta-infer-worker-host/src"
ACTOR = HOST / "control_actor.rs"
PORT = HOST / "control_port.rs"
LIB = HOST / "lib.rs"
RUN_CONTROL = HOST / "native_run_control.rs"
APP_SERVER = HOST / "native_app_server.rs"
WORKER_CLI = HOST / "bin/hepta-infer-worker.rs"
RECOVERY_CLI = HOST / "bin/hepta-infer-recovery.rs"
MAINTENANCE_CLI = HOST / "bin/hepta-infer-maintenance.rs"


def require(path: Path, markers: tuple[str, ...], failures: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            failures.append(f"{path.relative_to(ROOT)} missing {marker!r}")


def forbid(path: Path, markers: tuple[str, ...], failures: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker in text:
            failures.append(f"{path.relative_to(ROOT)} retains forbidden {marker!r}")


def check() -> None:
    failures: list[str] = []
    require(
        PORT,
        (
            "#[async_trait]",
            "pub trait NativeControlPort: Send + Sync",
            "impl NativeControlPort for DurableInferenceControl",
        ),
        failures,
    )
    require(
        ACTOR,
        (
            "impl NativeControlPort for NativeJournalWriterHandle",
            "prepare_dispatch_raw",
            "prepare_authorized_dispatch_raw",
            "abort_raw",
            "reject_before_start",
            "settle_legacy",
            "NativeReconcilerActor",
        ),
        failures,
    )
    require(
        LIB,
        (
            "pub mod control_actor;",
            "pub mod control_port;",
            "pub use control_actor::NativeJournalWriterActor;",
            "pub use control_port::NativeControlPort;",
        ),
        failures,
    )
    for path in (RUN_CONTROL, APP_SERVER):
        require(path, ("&mut dyn NativeControlPort", ".await"), failures)
        forbid(
            path,
            (
                "&mut DurableInferenceControl",
                "use codex_hepta_infer_core::durable_control::DurableInferenceControl;",
            ),
            failures,
        )
    require(
        WORKER_CLI,
        (
            "NativeJournalWriterActor::spawn",
            "actor.shutdown().await",
            '"--profile" if value == "native-app-server" => {}',
            "The sole release profile is native-app-server and is selected by default.",
        ),
        failures,
    )
    forbid(
        WORKER_CLI,
        (
            "native_profile_selected",
            "--profile native-app-server must be selected explicitly",
        ),
        failures,
    )
    require(
        RECOVERY_CLI,
        (
            "NativeJournalWriterActor::spawn",
            "NativeReconcilerActor::new",
            "actor.shutdown().await",
        ),
        failures,
    )
    require(
        MAINTENANCE_CLI,
        (
            "NativeJournalWriterActor::spawn",
            ".metrics(",
            ".compact()",
            "actor.shutdown().await",
        ),
        failures,
    )
    for path in (WORKER_CLI, RECOVERY_CLI, MAINTENANCE_CLI):
        forbid(
            path,
            (
                "DurableInferenceControl::open",
                "use codex_hepta_infer_core::durable_control::DurableInferenceControl;",
            ),
            failures,
        )
    if failures:
        raise SystemExit("\n".join(failures))
    print("inference.control actor migration is current")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "apply"))
    args = parser.parse_args()
    try:
        check()
        if args.command == "apply":
            print({"changed": [], "status": "migration already materialized; verification only"})
    except OSError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
