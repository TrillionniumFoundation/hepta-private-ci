"""Independent held evaluation. Frozen models receive only the three allowed fields."""
from pathlib import Path
import hashlib
import json
import subprocess
import time

ROOT = Path("/workspace/scratch/e4725aa88375")
CELL = ROOT / "cell_semantics_v6/qualification/memory-cell-v6"
HELD = ROOT / "root_holdout_v6"
OUT = HELD / "results"
OUT.mkdir(exist_ok=True)
manifest = json.loads((CELL / "FREEZE.json").read_text())
assert hashlib.sha256((CELL / "FREEZE.json").read_bytes()).hexdigest() == "01c4327b3f950b821861bb5ed54c592aa385e277260b9ab203059e765b0c8244"
for rel, meta in manifest["files"].items():
    assert hashlib.sha256((CELL / rel).read_bytes()).hexdigest() == meta["sha256"], rel
raw = (HELD / "independent_held_requests.jsonl").read_bytes()
assert hashlib.sha256(raw).hexdigest() == manifest["independent_held_sha256"]
rows = [json.loads(line) for line in raw.splitlines()]
series = ["Mauna Loa CO2", "global temperature anomaly", "monthly sunspots", "unemployment rate"]
requests = [{"utterance": row["utterance"], "series_name": series[i % 4], "date": "2000-06"} for i, row in enumerate(rows)]
body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in requests)
(OUT / "serving_requests.jsonl").write_text(body)
model = CELL / manifest["selected"]["model"]
commands = {
    "v6_selected": ["python3", str(CELL / "native_router.py"), "--model", str(model), "--sha256", manifest["selected"]["artifact"]["sha256"]],
    "deterministic": ["python3", str(CELL / "native_router.py"), "--deterministic"],
    "v5_selected": ["python3", str(CELL / "serve.py"), "--v5-model", str(CELL / "evidence/baseline-v5/seed-8011/selected"), "--sha256", "dbeb0963bb2ccd49ebe6078bea44a7ce5d51cd7add5e29c87e9499e959989965"],
}
summary = {"held_sha256": manifest["independent_held_sha256"], "freeze_sha256": hashlib.sha256((CELL / "FREEZE.json").read_bytes()).hexdigest(), "unique_utterances": 180, "supported":120, "ood":60, "language":"en", "synthetic_assistant_authored":True, "results":{}}
for name, command in commands.items():
    metric_path = OUT / (name + ".resources.txt")
    wrapper = """import json,pathlib,resource,runpy,sys,time
metrics=pathlib.Path(sys.argv[1]);script=sys.argv[2];sys.argv=sys.argv[2:]
sys.path.insert(0,str(pathlib.Path(script).parent))
tick=time.perf_counter()
try:
 runpy.run_path(script,run_name="__main__")
finally:
 r=resource.getrusage(resource.RUSAGE_SELF)
 metrics.write_text("user_seconds="+str(r.ru_utime)+"\\nsystem_seconds="+str(r.ru_stime)+"\\nmax_rss_kib="+str(r.ru_maxrss)+"\\nelapsed_seconds="+str(time.perf_counter()-tick)+"\\n")
"""
    wrapped = [command[0], "-c", wrapper, str(metric_path), *command[1:]]
    tick = time.perf_counter()
    result = subprocess.run(wrapped, input=body, text=True, capture_output=True, cwd=ROOT / "cell_semantics_v6", timeout=120)
    wall = time.perf_counter() - tick
    (OUT / (name + ".stdout.jsonl")).write_text(result.stdout)
    (OUT / (name + ".stderr.txt")).write_text(result.stderr)
    assert result.returncode == 0, (name, result.stderr)
    decisions = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(decisions) == len(rows), (name, len(decisions))
    assert not any("error" in value for value in decisions), name
    known = [(row, value) for row, value in zip(rows, decisions) if row["expected_operation"]]
    ood = [(row, value) for row, value in zip(rows, decisions) if row["expected_operation"] is None]
    correct = sum(value["accepted_intent"] == row["expected_operation"] for row, value in known)
    wrong = sum(value["accepted_intent"] is not None and value["accepted_intent"] != row["expected_operation"] for row, value in known)
    false_accept = sum(value["accepted_intent"] is not None for row, value in ood)
    resources = {}
    for line in metric_path.read_text().splitlines():
        key, value = line.split("=", 1)
        resources[key] = float(value)
    rates = {"correct":correct, "known_rejected":120-correct-wrong, "known_wrong":wrong, "correct_coverage":correct/120, "ood_false_accept":false_accept, "ood_false_accept_rate":false_accept/60, "gate_pass":correct>=96 and false_accept<=3, "wall_seconds_including_process_start":wall, "resources_one_router_process":resources}
    rates["per_operation"] = {op:sum(value["accepted_intent"] == op for row, value in known if row["expected_operation"] == op) for op in ("at","previous","change","mean3","range3","peak3")}
    if all("inference_ns" in value for value in decisions):
        values = sorted(value["inference_ns"] for value in decisions)
        rates["inference_ms_p50"] = values[len(values)//2] / 1e6
        rates["inference_ms_p95"] = values[int(len(values)*0.95)-1] / 1e6
    summary["results"][name] = rates
    print(json.dumps({name:rates}), flush=True)
for rel, meta in manifest["files"].items():
    assert hashlib.sha256((CELL / rel).read_bytes()).hexdigest() == meta["sha256"], rel
(OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")

