"""Generate exact closed sets from this isolated, explicitly scoped plan."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
from pprint import pformat
import re
import sys
import tomllib

root = Path(__file__).resolve().parent
overlay = root / "overlay"
plan = json.loads((root / "CALLERS_DELTA_PLAN.json").read_text())
manifest = tomllib.loads((overlay / "CALLERS.toml").read_text())
rows = {row["id"]: row for row in manifest["boundary"]}
expected = {row["id"]: tuple(rows[row["id"]]["product_callers"]) for row in plan["boundary_changes"]}
paths = sorted({row["path"] for row in plan["protected_changes"]})
spec = importlib.util.spec_from_file_location("progress_source_proof", overlay / "scripts/verify_hepta_callers.py")
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)
functions = {}
for path in paths:
    code = proof._strip_cfg_test_items(proof._strip_rust_non_code((overlay / path).read_text()))
    functions[path] = dict(Counter(re.findall(r"\bfn\s+([A-Za-z_]\w*)\s*(?:<|\()", code)))
text = (root / "test_evaluated_version_source_closure.template.py").read_text()
for marker, value in (("__EXPECTED__", expected), ("__FUNCTIONS__", functions), ("__OWN_PATHS__", paths)):
    assert text.count(marker) == 1, marker
    text = text.replace(marker, pformat(value, width=100, sort_dicts=True))
compile(text, "test_evaluated_version_source_closure.py", "exec")
(overlay / "qa/b4-no-bypass/test_evaluated_version_source_closure.py").write_text(text)
print(json.dumps({"boundaries": len(expected), "paths": len(paths), "source_test_functions": text.count("    def test_")}))
