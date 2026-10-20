#!/usr/bin/env bash
# Invoked by the required security-backport lane inside dbus-run-session.
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP must name the job temporary directory}"
: "${DBUS_SESSION_BUS_ADDRESS:?start this script with dbus-run-session}"
qualification_root="$(mktemp -d "$RUNNER_TEMP/keyring-qualification.XXXXXX")"
export XDG_DATA_HOME="$qualification_root/data"
export XDG_RUNTIME_DIR="$qualification_root/runtime"
export XDG_CONFIG_HOME="$qualification_root/config"
export XDG_CACHE_HOME="$qualification_root/cache"
unset GNOME_KEYRING_CONTROL
install -d -m 0700 "$XDG_DATA_HOME" "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME"
monitor_log="$RUNNER_TEMP/security-backports-open-session.log"

# This password protects only this job's disposable test keyring.
printf '%s' 'hepta-ci-ephemeral-password' | \
    gnome-keyring-daemon --unlock --daemonize --components=secrets

python3 - <<'PY'
import re
import subprocess
import time

deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    result = subprocess.run(
        [
            "dbus-send", "--session", "--print-reply", "--reply-timeout=1000",
            "--dest=org.freedesktop.secrets", "/org/freedesktop/secrets",
            "org.freedesktop.Secret.Service.ReadAlias", "string:default",
        ],
        capture_output=True, text=True, timeout=2,
    )
    collection = re.search(
        r'^\s*object path "(/org/freedesktop/secrets/collection/[^\"]+)"\s*$',
        result.stdout, re.MULTILINE,
    )
    if result.returncode == 0 and collection:
        locked = subprocess.run(
            [
                "dbus-send", "--session", "--print-reply", "--reply-timeout=1000",
                "--dest=org.freedesktop.secrets", collection[1],
                "org.freedesktop.DBus.Properties.Get",
                "string:org.freedesktop.Secret.Collection", "string:Locked",
            ],
            capture_output=True, text=True, timeout=2,
        )
        if locked.returncode == 0 and re.search(
            r'^\s*variant\s+boolean false\s*$', locked.stdout, re.MULTILINE,
        ):
            break
    time.sleep(0.1)
else:
    raise SystemExit("Secret Service did not expose an unlocked default collection before the deadline")
PY

: > "$monitor_log"
stdbuf -oL dbus-monitor --session \
    "type='method_call',interface='org.freedesktop.Secret.Service',member='OpenSession'" \
    "type='signal',path='/org/hepta/SecurityQualification',interface='org.hepta.SecurityQualification',member='MonitorBarrier'" \
    > "$monitor_log" 2>&1 &
monitor_pid=$!
trap 'kill "$monitor_pid" 2>/dev/null || true; wait "$monitor_pid" 2>/dev/null || true' EXIT

# A marker observed on this same bus proves subscription at the start and
# drains preceding matching messages at the end, before terminating the monitor.
wait_for_monitor_barrier() {
python3 - "$monitor_log" "$monitor_pid" "$1" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

log = Path(sys.argv[1])
phase = sys.argv[3]
nonce = f"{phase}-{uuid.uuid4()}"
fields = (
    "path=/org/hepta/SecurityQualification;",
    "interface=org.hepta.SecurityQualification;",
    "member=MonitorBarrier",
)
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    os.kill(int(sys.argv[2]), 0)
    subprocess.run(
        [
            "dbus-send", "--session", "--type=signal",
            "/org/hepta/SecurityQualification",
            "org.hepta.SecurityQualification.MonitorBarrier", f"string:{nonce}",
        ],
        check=True, capture_output=True, text=True, timeout=2,
    )
    lines = log.read_text().splitlines()
    if any(
        header.startswith("signal ") and all(field in header for field in fields)
        and value.strip() == f'string "{nonce}"'
        for header, value in zip(lines, lines[1:])
    ):
        receipt = {"phase": phase, "nonce": nonce, "observed": True}
        (log.parent / f"security-backports-monitor-{phase}.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        print(json.dumps(receipt))
        break
    time.sleep(0.05)
else:
    raise SystemExit(f"D-Bus monitor did not observe the {phase} barrier before the deadline")
PY
}

wait_for_monitor_barrier start

just test --locked -p codex-keyring-store \
    --features codex-keyring-store/secret-service-qualification \
    --test secret_service --test-threads=1 --retries=0 --no-tests=fail

wait_for_monitor_barrier end
kill "$monitor_pid"
wait "$monitor_pid" || true
trap - EXIT

python3 - "$monitor_log" "$RUNNER_TEMP/security-backports-negotiation.json" <<'PY'
import json
from pathlib import Path
import re
import sys

algorithms = []
awaiting_algorithm = False
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.startswith("method call "):
        if awaiting_algorithm:
            raise SystemExit("OpenSession call had no observed algorithm")
        awaiting_algorithm = "member=OpenSession" in line
    elif awaiting_algorithm:
        match = re.fullmatch(r'\s*string "([^"]+)"', line)
        if match:
            algorithms.append(match[1])
            awaiting_algorithm = False
expected = "dh-ietf1024-sha256-aes128-cbc-pkcs7"
passed = bool(algorithms) and not awaiting_algorithm and all(
    algorithm == expected for algorithm in algorithms
)
result = {"open_session_algorithms": algorithms, "passed": passed}
Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
if not passed:
    raise SystemExit("every observed Secret Service session must negotiate DH encryption")
PY
