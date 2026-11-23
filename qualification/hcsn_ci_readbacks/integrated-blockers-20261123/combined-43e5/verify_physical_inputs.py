"""Check all caller inputs against the original c6a set and the official changed Git trees."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
repo = HERE / "physical"
expected = json.loads((HERE / "official-inputs.json").read_text())

def blob(path):
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()

def inventory_hash(records):
    rows = [f"{name}\t{records[name]}\n" for name in sorted(records)]
    return hashlib.sha256("".join(rows).encode()).hexdigest()

actual = {p.relative_to(repo).as_posix():blob(p) for p in (repo/"codex-rs").rglob("*.rs")}
assert len(actual) == 9141
old = actual.copy()
for path, before, after in expected["changed"]:
    assert before and after and actual[path] == after
    old[path] = before
assert inventory_hash(old) == expected["base_rust_digest"]
assert all(blob(repo/path) == digest for path,digest in expected["guard_files"].items())
print(json.dumps({"source":expected["candidate"],"rust_files":len(actual), "rust_set_sha256":inventory_hash(actual),
    "old_source":expected["base"],"old_rust_set_sha256":inventory_hash(old), "changed_rust_files":len(expected["changed"]),
    "guard_input_git_blobs":expected["guard_files"]}, indent=2, sort_keys=True))
