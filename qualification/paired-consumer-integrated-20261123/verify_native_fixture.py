"""Reconstruct both scopes for two archived engineering model runs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

binary, package, reference = map(Path, sys.argv[1:])
known = json.loads(reference.read_bytes())

def sha(value):
    return hashlib.sha256(value).hexdigest()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

assert sha(package.read_bytes()) == known["fixture_archive_sha256"]
observed = {}
with zipfile.ZipFile(package) as z:
    for path in z.namelist():
        if not path.endswith("/OUTCOME.json"):
            continue
        end = json.loads(z.read(path))
        start = json.loads(z.read(path.removesuffix("OUTCOME.json") + "STARTED.json"))
        for name, scope in (("request", start["request"]), ("report", end["scope"])):
            key = end["scope"]["outcome"], name
            study = end["grant"]["study_sha256"]
            request = {"study_sha256":study, "scope":scope}
            preview = subprocess.run([binary,"--print-statement"],input=canonical(request),
                                     capture_output=True,check=True,timeout=10).stdout
            ref = next(row for row in known["statements"] if (row["decision"],row["kind"])==key)
            assert sha(canonical(request))==ref["scope_sha256"]
            assert preview==ref["native_statement"].encode() and sha(preview)==ref["native_statement_sha256"]
            rejected = subprocess.run([binary,"1","/invalid","/invalid"],input=canonical({
                **request, "delivery_id":end["grant"]["delivery_id"]
            }),capture_output=True,close_fds=True,timeout=10)
            assert rejected.returncode!=0 and rejected.stdout==b""
            assert key not in observed
            observed[key] = sha(preview)
assert len(observed)==4
print(json.dumps({"verified_scopes":len(observed),"original_zip_sha256":known["fixture_archive_sha256"],
                  "binary_sha256":sha(binary.read_bytes()), "true_human_receipts":0},sort_keys=True))
