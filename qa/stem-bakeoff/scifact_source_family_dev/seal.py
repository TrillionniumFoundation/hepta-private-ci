"""Create a fresh local material seal before running retrieval; never overwrite."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    paths = [ROOT / name for name in ["protocol.json", "protocol.sha256", "acquire.py", "prepare.py", "retrieve.py", "score.py", "seal.py", "test_retrieval.py"]]
    paths += sorted(p for directory in ["local-data", "prepared"] for p in (ROOT / directory).iterdir() if p.is_file())
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "stage": "before_retrieval_and_scoring", "prospective_registration": False, "files": [{"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
    with (ROOT / "material-seal.json").open("x") as output:
        json.dump(manifest, output, sort_keys=True, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
