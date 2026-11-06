"""Reproduce local software checks only; no external model endpoint or actual bill is used."""
import hashlib
import importlib
import json
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile
import time
from .confirmation import evaluate
from .contracts import canonical, stamp
from .ledger import complete_events
from .tasks import method_digest
from .test_confirmation import synthetic

MODULES = ("test_transport", "test_confirmation", "test_tasks", "test_gate_contracts", "test_ledger", "test_policy")
ORIGINAL_SHA256 = "d9af64b97a57b483a76ebc37f15148eea9465186321400d1049be6df18d2a661"


def main():
    root, started, began = Path(__file__).resolve().parent, stamp(), time.perf_counter()
    repo = root.parents[4]
    original = root/"evidence/qualification-original.json"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == ORIGINAL_SHA256
    paths = sorted([p for p in root.iterdir() if p.suffix in (".py", ".json", ".md")]
                   + [root/"evidence/current_gate.json", original, root/"evidence/qualification-before-clock-review.json"])
    def hashes():
        return {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = hashes()
    command = [sys.executable, "-m", "unittest", *[__package__+"."+m for m in MODULES], "-v"]
    cpu0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    test_start = time.perf_counter()
    run = subprocess.run(command, cwd=repo, capture_output=True, text=True)
    test_wall = time.perf_counter()-test_start
    cpu1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    match = re.search(r"Ran (\d+) tests in ([\d.]+)s", run.stderr)
    receipt = {"schema": "ndu.confirmation.qualification.v2", "started_at": started,
        "scope": "New confirmation package only; original study suites and external_smoke not repeated",
        "reproduce_command": "python -m "+__package__+".qualify", "command": command,
        "display_command": "python -m unittest "+" ".join(__package__+"."+m for m in MODULES)+" -v",
        "cwd": str(repo), "exit_code": run.returncode, "wall_seconds": test_wall,
        "child_cpu_seconds": cpu1.ru_utime+cpu1.ru_stime-cpu0.ru_utime-cpu0.ru_stime,
        "tests_run": int(match.group(1)) if match else None,
        "unittest_reported_seconds": float(match.group(2)) if match else None,
        "stdout": run.stdout, "stderr": run.stderr, "python": sys.version, "platform": sys.platform,
        "source_sha256_before": before, "original_receipt_sha256": ORIGINAL_SHA256,
        "independent_review": "Separate review artifact required; this receipt records reproducible checks"}
    bundle = synthetic()
    if importlib.util.find_spec("jsonschema"):
        import jsonschema
        schema = json.loads((root/"schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(bundle, schema)
        receipt["reference_schema_check"] = {"valid": True, "synthetic_fixture_matches": True}
    else:
        receipt["reference_schema_check"] = {"status": "NOT_RUN", "dependency": "optional jsonschema"}
    receipt["synthetic_mathematics_only_gate"] = {"status": evaluate(**bundle)["status"],
        "not_llm_evidence": True, "note": "Fabricated records and proof materials exercise arithmetic and rejection only"}
    with tempfile.TemporaryDirectory(prefix="ndu_cli_fixture_") as directory:
        d = Path(directory)
        task = {"id": "cli-fixture", "prompt": "Return ten", "expected_answer": "ten",
                "tools": {}, "planning_model": {"hypotheses": []}}
        code = "import json;print(json.dumps({'model_id':'fixture','revision':'test-v1','text':'{\"answer\":\"ten\"}','usage':{'input_tokens':1,'output_tokens':1}}))"
        provider = {"kind": "local", "identity": {"kind": "offline_fixture", "model_id": "fixture", "revision": "test-v1"},
                    "argv": [sys.executable, "-c", code]}
        settings = {"deadline_seconds": 3., "call_timeout_seconds": 1., "reserve_model_seconds": .2,
                    "max_tools": 2, "fixed_budget": 1, "currency_to_score": 1., "time_price": 0.}
        settings.update(protocol_sha256="0"*64, method_sha256=method_digest("direct_stop", settings))
        for filename, value in (("task", task), ("provider", provider), ("settings", settings)):
            (d/(filename+".json")).write_text(canonical(value))
        cli_command = [sys.executable, "-m", __package__+".tasks", "--task", str(d/"task.json"),
            "--provider", str(d/"provider.json"), "--settings", str(d/"settings.json"),
            "--arm", "direct_stop", "--ledger", str(d/"ledger.jsonl"), "--output", str(d/"episode.json")]
        cli = subprocess.run(cli_command, cwd=repo, capture_output=True, text=True)
        episode = json.loads((d/"episode.json").read_text())
        raw = [json.loads(line) for line in (d/"ledger.jsonl").read_text().splitlines()]
        events = complete_events(raw)
        receipt["cli_fixture_smoke"] = {"exit_code": cli.returncode, "stdout": cli.stdout, "stderr": cli.stderr,
            "not_llm_evidence": True, "terminal": episode["terminal"], "quality": episode["quality"],
            "raw_phases": [e["phase"] for e in raw], "request_kinds": [e["kind"] for e in events],
            "all_actual_charges_unknown": all(e["actual_amount"] is None for e in events),
            "scientific_status": episode["scientific_status"]}
        assert cli.returncode == 0 and episode["terminal"] == "delivered" and episode["quality"] == 1
        assert [e["kind"] for e in events] == ["model", "verifier", "host_envelope"]
        assert episode["scientific_status"] == "NOT_LLM_EVIDENCE"
    receipt.update(source_sha256_after=hashes(), real_llm_calls=0, paid_external_api_calls=0,
        network_scope="Loopback HTTP fixture only; no external endpoint", actual_currency_cost=None,
        cost_note="Local software verification CPU/wall recorded; monetary price and invoices unknown",
        current_confirmation_gate=json.loads((root/"evidence/current_gate.json").read_text()),
        python_line_counts={p.name: len(p.read_text().splitlines()) for p in paths if p.suffix == ".py"},
        development_history=[{"kind": "superseded_checks", "detail": "Original 19-test receipt predates four independent-review blockers"},
            {"kind": "command_typo", "prior_exit_code": 1, "detail": "An old mixed dotted/slash test module name caused one loader error; the corrected module passed"},
            {"kind": "additional_review_counterexample", "detail": "Independent review found dispatch/response and interval/order holes; all counterexamples were retained and regression-tested"}],
        finished_at=stamp(), total_qualification_wall_seconds=time.perf_counter()-began)
    receipt["source_unchanged_during_qualification"] = before == receipt["source_sha256_after"]
    assert run.returncode == 0 and receipt["tests_run"] == 39 and receipt["source_unchanged_during_qualification"]
    (root/"evidence/qualification.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(canonical({k: receipt[k] for k in ("tests_run", "exit_code", "wall_seconds", "child_cpu_seconds",
        "source_unchanged_during_qualification", "real_llm_calls")}))


if __name__ == "__main__":
    main()
