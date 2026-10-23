"""Explicit bounded original-publisher acquisition; no model/script execution."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
PINS = {
    "data.tar.gz": "11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be",
    "claims_with_citances.jsonl": "a12af8640b5079dc6ceccbf1a31e755b28158643ddd1928f91b92caa0c388704",
}


def main():
    destination = ROOT / "local-data"
    destination.mkdir(exist_ok=False)
    manifest = {"requests": [], "status": "STARTED"}
    try:
        for name, expected in PINS.items():
            url = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/" + name
            request = urllib.request.Request(url, headers={"User-Agent": "HeptaSciFactDevelopment/0.1 (bounded research; https://github.com/TrillionniumFoundation/hepta-private-ci)"})
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read(8388609)
                record = {"url": url, "status": response.status, "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified"), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            manifest["requests"].append(record)
            assert len(body) <= 8388608 and record["sha256"] == expected, "Pinned public source changed or exceeded cap"
            output_name = name if name == "data.tar.gz" else "citances-local-only.jsonl"
            (destination / output_name).write_bytes(body)
            if name == "data.tar.gz":
                with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
                    assert sum(m.size for m in archive.getmembers()) <= 33554432
                    for member_name in ["data/corpus.jsonl", "data/claims_train.jsonl", "data/claims_dev.jsonl"]:
                        member = archive.getmember(member_name)
                        assert member.isfile()
                        (destination / Path(member_name).name).write_bytes(archive.extractfile(member).read())
        manifest["status"] = "COMPLETE"
    except Exception as error:
        manifest.update(status="STOPPED_NO_RETRY", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        (destination / "acquisition.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
