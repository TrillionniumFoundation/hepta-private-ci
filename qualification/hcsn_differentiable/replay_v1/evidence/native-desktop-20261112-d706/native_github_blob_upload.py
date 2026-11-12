import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

root = Path("/home/qian-qi/hcsn-c2-real-replay-20261112-d706-attempt001")
outcome = root / "GITHUB_BLOB_UPLOAD.json"
if outcome.exists():
    print(outcome.read_text(), flush=True)
    raise SystemExit(0)
def save(value):
    with outcome.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(value, sort_keys=True), flush=True)
exe = shutil.which("gh")
if not exe:
    save({"status": "unavailable", "reason": "gh_not_installed", "upload_attempted": False})
    raise SystemExit(2)
login = subprocess.run([exe, "api", "user", "--jq", ".login"], capture_output=True, text=True, timeout=25)
if login.returncode != 0 or login.stdout.strip().lower() != "profhepta":
    save({"status": "unavailable", "reason": "existing_gh_identity_not_verified_as_ProfHepta",
          "auth_query_exit": login.returncode, "upload_attempted": False})
    raise SystemExit(2)
archive = root / "NATIVE_ORIGINALS.zip"
raw = archive.read_bytes()
expected_sha256 = "d17e71b766631f3789dcb43bdd312dacfbc4ea0ce7e4fc14074587584900a2fe"
if len(raw) != 10976581 or hashlib.sha256(raw).hexdigest() != expected_sha256:
    raise ValueError("bound native archive differs")
expected_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
intent = {"repository": "TrillionniumFoundation/hepta-private-ci", "expected_blob_sha": expected_blob,
          "archive_sha256": expected_sha256, "archive_bytes": len(raw),
          "authenticated_login": login.stdout.strip(), "started_unix_ns": time.time_ns(),
          "operation": "create immutable Git blob only; no ref/PR change"}
with (root / "GITHUB_BLOB_UPLOAD_INTENT.json").open("x") as stream:
    json.dump(intent, stream, indent=2, sort_keys=True)
    stream.write("\n")
payload = json.dumps({"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"})
started = time.monotonic()
try:
    result = subprocess.run([exe, "api", "repos/TrillionniumFoundation/hepta-private-ci/git/blobs",
                             "--method", "POST", "--input", "-"],
                            input=payload, text=True, capture_output=True, timeout=180)
except subprocess.TimeoutExpired:
    save({**intent, "status": "unknown", "upload_attempted": True, "reason": "gh_api_timeout",
          "automatic_retry": False, "wall_seconds": time.monotonic() - started})
    raise SystemExit(3)
if result.returncode != 0:
    save({**intent, "status": "failed", "upload_attempted": True, "exit_code": result.returncode,
          "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
          "wall_seconds": time.monotonic() - started})
    raise SystemExit(4)
response = json.loads(result.stdout)
if response.get("sha") != expected_blob:
    raise ValueError("GitHub blob response differs from actual bytes")
save({**intent, "status": "succeeded", "upload_attempted": True,
      "blob_sha": response["sha"], "blob_url": response["url"], "wall_seconds": time.monotonic() - started})

