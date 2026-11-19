"""The overlay is derived from the separately reviewed experimental schema artifact."""

import importlib.util
import json
import sys
from pathlib import Path

SDK_ROOT = Path(__file__).resolve().parents[1]
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

from scripts._process_observation.schema import render_overlay  # noqa: E402


def test_process_observation_matches_source_bound_experimental_fixture():
    fixtures = SDK_ROOT / "tests" / "fixtures" / "process_observation"
    schema = (fixtures / "schema.json").read_bytes()
    provenance = json.loads((fixtures / "source.json").read_text())
    actual = render_overlay(schema, provenance)
    expected = SDK_ROOT / "src" / "openai_codex" / "generated" / "process_observation.py"
    assert actual == expected.read_text()

    spec = importlib.util.spec_from_file_location("reviewed_process_overlay", expected)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    payload = module.ProcessIndeterminateNotification.model_validate(
        {
            "processHandle": "observed-owner",
            "reason": "exitObservationLost",
            "stdout": "observed bytes",
            "stdoutCapReached": False,
            "stderr": "",
            "stderrCapReached": True,
        }
    )
    assert payload.model_dump(by_alias=True, mode="json") == {
        "processHandle": "observed-owner",
        "reason": "exitObservationLost",
        "stdout": "observed bytes",
        "stdoutCapReached": False,
        "stderr": "",
        "stderrCapReached": True,
    }
