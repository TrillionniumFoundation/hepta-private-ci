"""Draw the one future seed after the student state is sealed; export blinded inputs."""
import json
from pathlib import Path
import secrets

from panel import digest, panel

root = Path("work")
assert (root / "freeze.json").is_file()
seed = root / "confirmation-seed.json"
if not seed.exists():
    with seed.open("x") as f:
        json.dump({"seed": secrets.token_hex(24)}, f)
rows = [r for r in panel() if r["split"] in ("holdout","composition","old-test")]
blind = [{k:r[k] for k in ("id", "query", "candidates", "domain")} for r in rows]
assert len(blind) == 272 and len({r["id"] for r in blind}) == len(blind)
(root / "blind.json").write_text(json.dumps(blind, sort_keys=True))
print("E3_LOCKED_PANEL", digest(rows), len(rows))
