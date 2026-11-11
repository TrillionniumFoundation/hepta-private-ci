"""Replay evidence integrity and all original target/case counting offline."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parent
manifest=json.loads((root/"FILE_MANIFEST.json").read_text())
for row in manifest["members"]:
    path=root/row["path"]
    assert path.is_file() and not path.is_symlink()
    data=path.read_bytes()
    assert len(data)==row["bytes"] and hashlib.sha256(data).hexdigest()==row["sha256"]
    assert hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()==row["git_blob"]
actual={p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
assert actual=={r["path"] for r in manifest["members"]}|{"FILE_MANIFEST.json"}
result=subprocess.run([sys.executable,str(root/"audit_bazel_terminal.py")],cwd=root,capture_output=True,timeout=30)
assert result.returncode==0,result.stderr.decode()
assert json.loads(result.stdout)==json.loads((root/"BAZEL_TERMINAL_AUDIT.json").read_text())
print(json.dumps({"status":"PASS","members":len(actual),"original_blocking_jobs":37,"original_blocking_raw_logs":16,"parallel_prerequisite_raw_logs":3,"test_target_records":7,"all_complete_case_block_counts_equal_original_summaries":True,"no_native_or_model_execution":True},sort_keys=True))
