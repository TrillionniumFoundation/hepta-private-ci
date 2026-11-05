import json
import sys
from pathlib import Path

import pytest

from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex.errors import CodexError
from openai_codex.models import UnknownNotification

MOCK_SERVER = r"""
import json, sys
record, echo = sys.argv[1:]
echo = json.loads(echo)
with open(record, "w", encoding="utf-8") as log:
    for line in sys.stdin:
        message = json.loads(line)
        log.write(json.dumps(message) + "\n")
        log.flush()
        if "id" not in message:
            continue
        result = {}
        if message["method"] == "initialize":
            result["userAgent"] = "process-fixture/1"
            if echo is not None:
                result["processIndeterminate"] = echo
        print(json.dumps({"id": message["id"], "result": result}), flush=True)
        if message["method"] == "process/spawn":
            print(json.dumps({"method": "process/indeterminate", "params": {
                "processHandle": "fixture", "reason": "exitObservationLost",
                "stdout": "seen", "stdoutCapReached": False,
                "stderr": "", "stderrCapReached": False
            }}), flush=True)
"""


@pytest.mark.parametrize("echo", [None, False, True])
def test_process_capability_uses_the_actual_initialize_echo_before_any_request(
    tmp_path: Path, echo: object
) -> None:
    record = tmp_path / "wire.jsonl"
    config = CodexConfig(
        experimental_api=True,
        launch_args_override=[
            sys.executable,
            "-I",
            "-u",
            "-c",
            MOCK_SERVER,
            str(record),
            json.dumps(echo),
        ],
    )
    with CodexClient(config) as client:
        client.initialize()
        if echo is True:
            assert client._request_raw("process/spawn", {"processHandle": "fixture"}) == {}
            event = client.next_notification()
            assert event.method == "process/indeterminate"
            assert not isinstance(event.payload, UnknownNotification)
            assert event.payload.model_dump(by_alias=True) == {
                "processHandle": "fixture",
                "reason": "exitObservationLost",
                "stdout": "seen",
                "stdoutCapReached": False,
                "stderr": "",
                "stderrCapReached": False,
            }
        else:
            with pytest.raises(CodexError, match="processIndeterminate initialize confirmation"):
                client._request_raw("process/spawn", {"processHandle": "fixture"})
            # This response establishes an actual pipe barrier after the local rejection.
            assert client._request_raw("server/diagnostics", {}) == {}
    frames = [json.loads(line) for line in record.read_text().splitlines()]
    assert frames[0]["params"]["capabilities"]["processIndeterminate"] is True
    assert [frame["method"] for frame in frames] == [
        "initialize",
        "initialized",
        "process/spawn" if echo is True else "server/diagnostics",
    ]


def test_non_boolean_process_confirmation_is_rejected_before_initialized(tmp_path: Path) -> None:
    record = tmp_path / "invalid-echo.jsonl"
    config = CodexConfig(
        experimental_api=True,
        launch_args_override=[sys.executable, "-I", "-u", "-c", MOCK_SERVER, str(record), "1"],
    )
    with CodexClient(config) as client:
        with pytest.raises(ValueError):
            client.initialize()
        with pytest.raises(CodexError, match="processIndeterminate initialize confirmation"):
            client._request_raw("process/spawn", {"processHandle": "fixture"})
    frames = [json.loads(line) for line in record.read_text().splitlines()]
    assert [frame["method"] for frame in frames] == ["initialize"]
