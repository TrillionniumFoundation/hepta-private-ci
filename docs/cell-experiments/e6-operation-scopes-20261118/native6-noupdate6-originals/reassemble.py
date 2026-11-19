from pathlib import Path
import hashlib,json
base=Path(__file__).resolve().parent
manifest=json.loads((base/"PARTS.json").read_text())
output=base/manifest["filename"]
assert output.parent==base and not output.exists()
whole=hashlib.sha256();count=0
with output.open("xb") as target:
 for row in manifest["parts"]:
  path=base/row["path"]
  assert path.parent==base
  raw=path.read_bytes()
  assert len(raw)==row["bytes"] and hashlib.sha256(raw).hexdigest()==row["sha256"]
  target.write(raw);whole.update(raw);count+=len(raw)
assert count==manifest["bytes"] and whole.hexdigest()==manifest["sha256"]
print(str(output))
