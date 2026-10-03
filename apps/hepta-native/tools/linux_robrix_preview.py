#!/usr/bin/env python3
"""Observe the isolated Linux Robrix developer preview; never qualify a release."""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time

PREFIX = "HEPTA_NATIVE_PREVIEW "


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observations(text):
    records = []
    for line in text.splitlines():
        if line.startswith(PREFIX):
            record = json.loads(line[len(PREFIX) :])
            if not isinstance(record, dict) or not isinstance(record.get("event"), str):
                raise ValueError("Malformed renderer observation")
            records.append(record)
    return records


def rectangle(value, size):
    if not isinstance(value, list) or len(value) != 4 or len(size) != 2:
        raise ValueError("Missing actual renderer rectangle")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value + size):
        raise ValueError("Nonfinite renderer geometry")
    x, y, w, h = value
    if (
        min(w, h, *size) <= 0
        or min(x, y) < 0
        or x + w > size[0] + 0.01
        or y + h > size[1] + 0.01
    ):
        raise ValueError("Renderer control lies outside the actual window")
    return value


def ready_observation(records, startup):
    if startup.get("gui_frame_callback_completed") is not True:
        raise ValueError("Owner readiness callback missing")
    matched = None
    for index, draw in enumerate(records):
        if draw["event"] != "status_draw_list":
            continue
        identity = draw.get("identity", {})
        if (
            identity.get("sessionId") != startup["session"]["session_id"]
            or identity.get("sessionGeneration") != startup["session"]["generation"]
            or identity.get("digest") != startup["view_digest"]
            or identity.get("revision") != startup["view_revision"]
        ):
            continue
        if type(draw.get("glyphCount")) is not int or draw["glyphCount"] <= 0:
            raise ValueError("Status has no real glyph instances")
        if type(draw.get("callback")) is not int or draw["callback"] <= 0:
            raise ValueError("Invalid draw callback identity")
        if (
            type(draw.get("dpi")) not in (int, float)
            or not math.isfinite(draw["dpi"])
            or draw["dpi"] <= 0
        ):
            raise ValueError("Invalid renderer DPI")
        rectangle(draw.get("statusRect"), draw.get("innerSize", []))
        if draw.get("captionCloseRect") is not None:
            rectangle(draw["captionCloseRect"], draw.get("innerSize", []))
        if not isinstance(draw.get("status"), str) or not draw["status"].startswith(
            "Verified runtime"
        ):
            raise ValueError("Missing exact rendered status")
        for later in records[index + 1 :]:
            if later["event"] == "later_callback" and later.get("identity") == identity:
                if (
                    type(later.get("callback")) is not int
                    or later["callback"] <= draw["callback"]
                ):
                    raise ValueError("Readiness did not cross a later callback")
                matched = draw
                break
    if matched is None:
        raise ValueError("No matching real status draw and subsequent callback")
    return matched


def validate_exit(records, cause):
    expected = ["close_requested", "renderer_exit", "gui_loop_returned"]
    closing = [r for r in records if r["event"] in expected]
    if [r["event"] for r in closing] != expected:
        raise ValueError("Missing, repeated or reordered native close phases")
    close, exited, returned = closing
    if close.get("cause") != cause:
        raise ValueError("Different window close path observed")
    if (
        exited.get("runtimeClosed") is not True
        or exited.get("allTasksIdle") is not True
    ):
        raise ValueError("Runtime or owned workers did not close")
    if (
        exited.get("activationRequested") is not False
        or returned.get("activationRequested") is not False
    ):
        raise ValueError("Unexpected update activation request")
    return closing


def ci_identity(root, head, tree):
    names = [
        "SOURCE_SHA",
        "BASE_SHA",
        "WORKFLOW_SHA",
        "TESTED_SHA",
        "HEPTA_CI_LANE",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
    ]
    identity = {name: os.environ.get(name, "") for name in names}
    for name in names[:4]:
        if (
            not re.fullmatch(r"[0-9a-f]{40}", identity[name])
            or identity[name] == "0" * 40
        ):
            raise ValueError("Missing exact CI commit: " + name)
    for name in names[-2:]:
        if not identity[name].isdigit() or int(identity[name]) <= 0:
            raise ValueError("Missing exact CI run identity")
    if head != identity["TESTED_SHA"]:
        raise ValueError("Runtime source differs from CI subject")
    lane = identity["HEPTA_CI_LANE"]
    if lane == "source-head":
        if head != identity["SOURCE_SHA"]:
            raise ValueError("Head lane source mismatch")
    elif lane == "base-merge":
        parents = subprocess.check_output(
            ["git", "-C", str(root), "show", "-s", "--format=%P", head], text=True
        ).split()
        if parents != [identity["BASE_SHA"], identity["SOURCE_SHA"]]:
            raise ValueError("Merge subject has unexpected parents")
    else:
        raise ValueError("Unknown native preview lane")
    identity["sourceTree"] = tree
    return identity


def capture_geometry(draw, width, height):
    expected = [round(v * draw["dpi"]) for v in draw["innerSize"]]
    if any(abs(a - b) > 1 for a, b in zip(expected, [width, height])):
        raise ValueError("PNG/client size differs from rendered window geometry")
    if draw.get("captionCloseRect") is None:
        return None
    x, y, w, h = rectangle(draw["captionCloseRect"], draw["innerSize"])
    point = [round((x + w / 2) * draw["dpi"]), round((y + h / 2) * draw["dpi"])]
    if not (0 <= point[0] < width and 0 <= point[1] < height):
        raise ValueError("Caption click falls outside the captured window")
    return point


def check_health(text):
    if re.search(
        r"panicked at|ScriptError|shader (?:compil(?:e|ing|ation)|link(?:ing)?) (?:error|failed)|Unknown os op",
        text,
        re.I,
    ):
        raise ValueError(
            "Native renderer reported a panic/script/shader/platform error"
        )


class RecordedCommands:
    """Capture command outcomes without publishing credential error streams."""

    def __init__(self, out):
        self.out = out
        self.sequence = 0

    def __call__(self, command, **kwargs):
        self.sequence += 1
        credential = Path(command[0]).name == "hepta-native-credential"
        record = {"command": [str(arg) for arg in command], "sequence": self.sequence}
        timeout = kwargs.pop("timeout", 20)
        started = time.monotonic()
        result = None
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, **kwargs
            )
            record["exitCode"] = result.returncode
            if credential:
                record["credentialStreamsRedacted"] = True
                if result.returncode == 0:
                    value = json.loads(result.stdout)
                    operation, account = command[1:3]
                    if operation == "provision":
                        valid = (
                            set(value) == {"schema", "account", "token_digest"}
                            and value.get("schema")
                            == "hepta.native-gateway-credential-provision.v1"
                            and value.get("account") == account
                            and isinstance(value.get("token_digest"), str)
                            and re.fullmatch(r"[0-9a-f]{64}", value["token_digest"])
                        )
                    elif operation == "delete":
                        valid = (
                            set(value) == {"schema", "account", "deleted"}
                            and value.get("schema")
                            == "hepta.native-gateway-credential-delete.v1"
                            and value.get("account") == account
                            and value.get("deleted") is True
                        )
                    else:
                        valid = False
                    if not valid:
                        raise ValueError(
                            "Credential response did not match the safe public schema"
                        )
                    record["safeReceipt"] = value
            else:
                record.update(stdout=result.stdout, stderr=result.stderr)
            if result.returncode != 0:
                raise RuntimeError(
                    f"Command {self.sequence} failed with exit {result.returncode}"
                )
            return result
        except subprocess.TimeoutExpired as error:
            record.update(exitCode=None, timedOut=True)
            if credential:
                record["credentialStreamsRedacted"] = True
            else:

                def decoded(value):
                    return (
                        value.decode("utf-8", errors="replace")
                        if isinstance(value, bytes)
                        else (value or "")
                    )

                record.update(
                    stdout=decoded(error.stdout), stderr=decoded(error.stderr)
                )
            raise RuntimeError(f"Command {self.sequence} timed out") from None
        except OSError as error:
            record.update(
                exitCode=None, startFailed=True, errorType=type(error).__name__
            )
            raise RuntimeError(f"Command {self.sequence} could not start") from None
        except (ValueError, TypeError, KeyError):
            record["safeReceiptRejected"] = True
            # Never propagate an exception containing unvalidated credential text.
            raise RuntimeError(
                f"Command {self.sequence} returned an invalid credential receipt"
            ) from None
        finally:
            record["elapsedSeconds"] = time.monotonic() - started
            (self.out / f"command-{self.sequence:03}.json").write_text(
                json.dumps(record, indent=2) + "\n"
            )


def cleanup_independently(actions):
    results = []
    for name, action in actions:
        try:
            value = action()
            results.append({"stage": name, "passed": True, "result": value})
        except BaseException as error:
            results.append(
                {"stage": name, "passed": False, "errorType": type(error).__name__}
            )
    return results


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


PREVIEW_REQUIRED = {
    ("hepta-native", "ui::robrix_host::tests::" + name)
    for name in (
        "robrix_close_drains_the_original_owner_before_exit",
        "renderer_wake_keeps_the_original_history_worker_and_join",
        "renderer_failure_and_unconfirmed_exit_cannot_activate_update",
        "renderer_invalidation_discards_the_original_first_draw_witness",
        "renderer_failure_cancels_queued_readiness_before_owner_admission",
    )
} | {
    ("hepta-native::embedded_resources", name)
    for name in (
        "embedded_font_bytes_override_a_conflicting_real_file",
        "absent_embedded_resource_never_recovers_from_a_real_file",
        "source_export_is_exact_and_has_no_runtime_side_effects",
        "original_notices_are_readable_before_runtime_initialization",
    )
}


def verify_preview_tests(root, inventory_path, junit_path, receipt_path):
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("Existing preview test receipt")
    sys.path.insert(0, str(root / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location(
            "native_source_verifier", root / "scripts/hepta_native_lifecycle_ci.py"
        )
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
    finally:
        sys.path.pop(0)
    verifier.REQUIRED = verifier.REQUIRED | PREVIEW_REQUIRED
    result = verifier.verify_tests(json.loads(inventory_path.read_text()), junit_path)
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    tree = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], text=True
    ).strip()
    record = {
        "schema": "hepta.native-robrix-preview-tests.v1",
        "ciSubject": ci_identity(root, head, tree),
        "inventorySha256": digest(inventory_path),
        "junitSha256": digest(junit_path),
        "verifierSha256": digest(root / "scripts/hepta_native_lifecycle_ci.py"),
        "result": result,
        "previewRequired": [list(key) for key in sorted(PREVIEW_REQUIRED)],
        "rendererObserved": False,
    }
    write_json(receipt_path, record)
    return record


def load_legacy(root):
    path = root / "apps/hepta-native/tools/linux_product_qualification.py"
    spec = importlib.util.spec_from_file_location("native_linux_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_ready(startup_path, log_path, process, timeout=35):
    deadline = time.monotonic() + timeout
    latest = "No readiness file"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Native preview exited before readiness: {process.returncode}"
            )
        if startup_path.exists():
            try:
                startup = json.loads(startup_path.read_text())
                if startup.get("process_id") != process.pid:
                    raise ValueError("Stale startup process identity")
                records = observations(log_path.read_text())
                return startup, ready_observation(records, startup)
            except ValueError as error:
                latest = str(error)
        time.sleep(0.05)
    raise RuntimeError("Native preview readiness deadline: " + latest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--gateway", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify-tests-only", action="store_true")
    parser.add_argument("--test-inventory", type=Path, required=True)
    parser.add_argument("--test-junit", type=Path, required=True)
    parser.add_argument("--test-receipt", type=Path, required=True)
    args = parser.parse_args()
    root = args.source_root.resolve(strict=True)
    if args.verify_tests_only:
        verify_preview_tests(
            root, args.test_inventory, args.test_junit, args.test_receipt
        )
        return
    if args.build_root is None or args.gateway is None or args.out is None:
        parser.error("runtime observation requires --build-root, --gateway and --out")
    build = args.build_root.resolve(strict=True)
    if not os.environ.get("DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        parser.error("Use a fresh hosted Xvfb and dbus-run-session")
    legacy = load_legacy(root)
    run = legacy.run
    subject = json.loads((build / "native-preview-build-input.json").read_text())
    head = run(["git", "-C", str(root), "rev-parse", "HEAD"]).stdout.strip()
    tree = run(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"]).stdout.strip()
    if (
        subject.get("sourceSha") != head
        or subject.get("sourceTree") != tree
        or subject.get("qualification") is not False
    ):
        raise ValueError("Preview build subject does not match the tested source")
    bound = ci_identity(root, head, tree)
    test_receipt = json.loads(args.test_receipt.read_text())
    if (
        test_receipt.get("schema") != "hepta.native-robrix-preview-tests.v1"
        or test_receipt.get("ciSubject") != bound
        or test_receipt.get("inventorySha256") != digest(args.test_inventory)
        or test_receipt.get("junitSha256") != digest(args.test_junit)
        or test_receipt.get("previewRequired")
        != [list(key) for key in sorted(PREVIEW_REQUIRED)]
    ):
        raise ValueError("Missing exact-subject preview test evidence")
    if (
        digest(root / "apps/hepta-native/Cargo.lock") != subject["canonicalLockSha256"]
        or digest(root / "apps/hepta-native/Cargo.toml")
        != subject["canonicalNativeManifestSha256"]
    ):
        raise ValueError("Canonical preview inputs changed after build")
    out = args.out.resolve()
    if out.is_relative_to(root) or out.is_relative_to(build):
        raise ValueError(
            "Runtime evidence and working directory must be outside source/build"
        )
    out.mkdir(parents=True, exist_ok=False)
    run = RecordedCommands(out)
    home, runtime_dir, empty = out / "home", out / "runtime", out / "empty-cwd"
    for path in (home, runtime_dir, empty):
        path.mkdir(mode=0o700)
    binaries = out / "bin"
    binaries.mkdir()
    executable_hashes = {}
    initial = {
        "ciSubject": bound,
        "sourceSha": head,
        "sourceTree": tree,
        "buildInputSha256": digest(build / "native-preview-build-input.json"),
        "previewTestsSha256": digest(args.test_receipt),
        "executableSha256": executable_hashes,
    }
    write_json(out / "subject.json", initial)
    for name, source in [
        ("hepta-native", build / "target/debug/hepta-native"),
        ("hepta-native-credential", build / "target/debug/hepta-native-credential"),
        ("hepta-native-gateway", args.gateway.resolve(strict=True)),
    ]:
        destination = binaries / name
        shutil.copy2(source, destination)
        executable_hashes[name] = digest(destination)
        write_json(out / "subject.json", initial)
        if executable_hashes[name] != digest(source):
            raise ValueError("Executable copy changed")
    app, credential = binaries / "hepta-native", binaries / "hepta-native-credential"
    environment = dict(
        os.environ,
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local/share"),
        XDG_RUNTIME_DIR=str(runtime_dir),
        LANG="C.UTF-8",
        LC_ALL="C.UTF-8",
        HEPTA_NATIVE_PREVIEW_OBSERVE="1",
    )
    owner = out / "owner-fixture"
    before = {}
    account = "native.preview." + secrets.token_hex(12)
    gateway = keyring = gui = None
    deleted = False
    sessions = []
    failure = None
    receipt = None
    stage = "owner_fixture"
    try:
        before = legacy.provision_isolated_owner_fixture(owner)
        stage = "keyring_start"
        with (home / "keyring-private.log").open("w") as log:
            keyring = subprocess.Popen(
                [
                    "gnome-keyring-daemon",
                    "--foreground",
                    "--unlock",
                    "--components=secrets",
                    "--control-directory",
                    str(runtime_dir / "keyring"),
                ],
                env=environment,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
            )
            keyring.stdin.write(secrets.token_hex(24).encode() + b"\n")
            keyring.stdin.close()
        deadline = time.monotonic() + 20
        while True:
            if keyring.poll() is not None:
                raise RuntimeError("Isolated keyring exited before ownership")
            reply = run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.freedesktop.DBus",
                    "--object-path",
                    "/org/freedesktop/DBus",
                    "--method",
                    "org.freedesktop.DBus.NameHasOwner",
                    "org.freedesktop.secrets",
                ],
                env=environment,
            ).stdout
            if reply.strip() == "(true,)":
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Isolated keyring did not acquire its D-Bus name")
            time.sleep(0.05)
        provision = json.loads(
            run(
                [str(credential), "provision", account], env=environment, cwd=empty
            ).stdout
        )
        legacy.validate_provision_receipt(provision, account)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        address = f"127.0.0.1:{port}"
        legacy.write_endpoint(out, account, address)
        state = out / "shell-state"
        legacy.private_write(
            out / "config.json",
            json.dumps(
                {
                    "endpoint_manifest": str(out / "endpoint.json"),
                    "trusted_keys": str(out / "trusted-keys.json"),
                    "state_dir": str(state),
                }
            ).encode(),
        )
        stage = "gateway_start"
        with (out / "gateway.log").open("w") as log:
            gateway = subprocess.Popen(
                [
                    str(binaries / "hepta-native-gateway"),
                    "--listen",
                    address,
                    "--state-root",
                    str(owner),
                    "--auth-keyring-account",
                    account,
                ],
                env=environment,
                cwd=empty,
                stdout=log,
                stderr=log,
            )
        deadline = time.monotonic() + 20
        while True:
            if gateway.poll() is not None:
                raise RuntimeError("Gateway bootstrap failed")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        connection = json.loads(
            run(
                [str(app), "--config", str(out / "config.json"), "--check-connection"],
                env=environment,
                cwd=empty,
            ).stdout
        )
        for sample in range(2):
            stage = f"session_{sample}_startup"
            startup_path = state / "last-startup.json"
            startup_path.unlink(missing_ok=True)
            log_path = out / f"session-{sample}.log"
            with log_path.open("w") as log:
                gui = subprocess.Popen(
                    [str(app), "--config", str(out / "config.json")],
                    cwd=empty,
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
            startup, draw = wait_ready(startup_path, log_path, gui)
            write_json(
                out / f"session-{sample}-startup.json",
                {
                    "startup": startup,
                    "draw": draw,
                    "startupBindingAxes": [
                        "sessionId",
                        "sessionGeneration",
                        "digest",
                        "revision",
                    ],
                    "drawLaterIdentityAxes": [
                        "sessionId",
                        "sessionGeneration",
                        "generation",
                        "revision",
                        "digest",
                        "modules",
                    ],
                },
            )
            stage = f"session_{sample}_capture"
            window = run(
                ["xdotool", "search", "--sync", "--onlyvisible", "--pid", str(gui.pid)],
                env=environment,
            ).stdout.split()
            if len(window) != 1:
                raise ValueError("Expected exactly one visible native window")
            window = window[0]
            png = out / f"session-{sample}.png"
            run(["import", "-window", window, str(png)], env=environment)
            size = run(["identify", "-format", "%w %h", str(png)]).stdout.split()
            capture_geometry(draw, *(int(v) for v in size))
            after_capture = ready_observation(
                observations(log_path.read_text()), startup
            )
            for key in (
                "identity",
                "status",
                "statusRect",
                "captionCloseRect",
                "innerSize",
                "dpi",
            ):
                if after_capture[key] != draw[key]:
                    raise ValueError(
                        "Renderer geometry changed during screenshot capture"
                    )
            check_health(log_path.read_text())
            ocr = run(
                ["tesseract", str(png), "stdout", "-l", "eng", "--psm", "11"],
                timeout=30,
            ).stdout
            (out / f"session-{sample}.ocr.txt").write_text(ocr)
            for label in (r"Verified\s+runtime", r"Conversations", r"Aurora"):
                if not re.search(label, ocr, re.I):
                    raise ValueError(
                        "Actual native shared-chat/status screenshot is unreadable: "
                        + label
                    )
            stage = f"session_{sample}_close"
            cause = "os"
            legacy.close_native_window(window)
            try:
                exit_code = gui.wait(timeout=15)
            except subprocess.TimeoutExpired:
                write_json(
                    out / f"session-{sample}-exit.json",
                    {"exitCode": None, "timedOut": True},
                )
                raise
            write_json(
                out / f"session-{sample}-exit.json",
                {"exitCode": exit_code, "timedOut": False},
            )
            if exit_code != 0:
                raise ValueError(f"Native preview close failed: {exit_code}")
            check_health(log_path.read_text())
            records = observations(log_path.read_text())
            phases = validate_exit(records, cause)
            sessions.append(
                {
                    "cause": cause,
                    "startup": startup,
                    "draw": draw,
                    "closePhases": phases,
                    "exitCode": exit_code,
                    "pngSha256": digest(png),
                    "logSha256": digest(log_path),
                }
            )
            write_json(out / f"session-{sample}-complete.json", sessions[-1])
            gui = None
        if (
            len(
                {
                    connection["session"]["session_id"],
                    *(s["startup"]["session"]["session_id"] for s in sessions),
                }
            )
            != 3
        ):
            raise ValueError("Session identity reused across separate ordinary starts")
        stage = "gateway_stop_and_fixture_check"
        legacy.terminate(gateway)
        write_json(out / "gateway-exit.json", {"exitCode": gateway.poll()})
        gateway = None
        after = {name: digest(owner / "runtime-v2" / name) for name in before}
        write_json(
            out / "initial-fixture-file-check.json",
            {
                "scope": "Only the three initial fixture files; no whole-owner inventory claim",
                "before": before,
                "afterGatewayStop": after,
                "equal": before == after,
            },
        )
        if before != after:
            raise ValueError("Initial fixture file bytes changed after gateway stop")
        stage = "credential_delete"
        deletion = json.loads(
            run([str(credential), "delete", account], env=environment, cwd=empty).stdout
        )
        legacy.validate_delete_receipt(deletion, account)
        deleted = True
        receipt = {
            "schema": "hepta.native-robrix-linux-preview.v1",
            "ciSubject": bound,
            "sourceSha": head,
            "sourceTree": tree,
            "buildInputSha256": digest(build / "native-preview-build-input.json"),
            "previewTestsSha256": digest(args.test_receipt),
            "executableSha256": executable_hashes,
            "sessions": sessions,
            "initialFixtureFilesUnchangedAfterGatewayStop": True,
            "checkedFixtureFiles": sorted(before),
            "isolatedCredentialDeleted": True,
            "captionCloseTested": False,
            "captionCloseBoundary": "requiresWaylandCSD",
            "installedDefaultQualified": False,
            "physicalDisplayAccepted": False,
            "positiveUpdateActivationTested": False,
            "productionChatQualified": False,
            "release": False,
        }
    except BaseException as error:
        failure = error
    finally:

        def stop(process):
            running = process is not None and process.poll() is None
            legacy.terminate(process)
            code = process.poll() if process is not None else None
            if process is not None and code is None:
                raise RuntimeError("Process remains running after cleanup")
            return {"wasRunning": running, "returnCode": code}

        def remove_credential():
            if deleted:
                return {"alreadyDeleted": True}
            result = json.loads(
                run(
                    [str(credential), "delete", account], env=environment, cwd=empty
                ).stdout
            )
            legacy.validate_delete_receipt(result, account)
            return result

        def remove_private(path):
            if path.exists():
                shutil.rmtree(path)
            return {"removed": not path.exists()}

        cleanup = cleanup_independently(
            [
                ("gui", lambda: stop(gui)),
                ("gateway", lambda: stop(gateway)),
                ("credential", remove_credential),
                ("keyring", lambda: stop(keyring)),
                ("privateHome", lambda: remove_private(home)),
                ("privateOwner", lambda: remove_private(owner)),
                ("privateRuntime", lambda: remove_private(runtime_dir)),
            ]
        )
        complete = (
            failure is None
            and receipt is not None
            and all(item["passed"] for item in cleanup)
        )
        terminal = {
            "schema": "hepta.native-robrix-preview-terminal.v1",
            "ciSubject": bound,
            "passed": complete,
            "lastStage": stage,
            "errorType": type(failure).__name__ if failure else None,
            "completedSessions": len(sessions),
            "cleanup": cleanup,
        }
        write_json(out / "terminal.json", terminal)
        if complete:
            receipt["cleanup"] = cleanup
            write_json(out / "preview-receipt.json", receipt)
    if failure is not None:
        raise failure
    if not complete:
        raise RuntimeError("Native preview cleanup did not complete")


if __name__ == "__main__":
    main()
