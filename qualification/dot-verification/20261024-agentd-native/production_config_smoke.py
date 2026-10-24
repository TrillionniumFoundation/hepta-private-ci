"""Local fail-closed smoke, not authenticated production qualification."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parent
binary = root / "target/debug/codex-hepta-agentd"
cases = [
    ("missing_fleet", {}, [], "HEPTA_FLEET_ROOT is required"),
    ("help_without_fleet", {}, ["--help"], "HEPTA_FLEET_ROOT is required"),
    ("invalid_retrieval", {"HEPTA_COGNITIVE_RETRIEVAL_MODE": "allow-all"}, [], "must be compatibility or hnmf-required"),
    ("missing_agent", {"HEPTA_FLEET_ROOT": "/nonexistent"}, [], "HEPTA_AGENT_ID is required"),
    ("missing_generation", {"HEPTA_FLEET_ROOT": "/nonexistent", "HEPTA_AGENT_ID": "smoke"}, [], "HEPTA_AGENT_GENERATION is required"),
    ("invalid_generation", {"HEPTA_FLEET_ROOT": "/nonexistent", "HEPTA_AGENT_ID": "smoke", "HEPTA_AGENT_GENERATION": "invalid"}, [], "must be an unsigned integer"),
    ("missing_home", {"HEPTA_FLEET_ROOT": "/nonexistent", "HEPTA_AGENT_ID": "smoke", "HEPTA_AGENT_GENERATION": "1"}, [], "HEPTA_AGENT_HOME is required"),
]
results = []
with tempfile.TemporaryDirectory(prefix="agentd-deny-smoke-") as directory:
    for name, extra, args, expected in cases:
        env = {"PATH": os.defpath, "HOME": directory, "CODEX_HOME": directory, **extra}
        result = subprocess.run([str(binary), *args], env=env, cwd=directory, capture_output=True, text=True, timeout=15)
        passed = result.returncode != 0 and expected in result.stderr and not list(Path(directory).iterdir())
        results.append({"case": name, "passed": passed, "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        print(json.dumps(results[-1]))
(root / "evidence/production-config-smoke.json").write_text(json.dumps(results, indent=2) + "\n")
assert all(row["passed"] for row in results), "fail-closed smoke failed"
