"""Provision exact licensed CJK assets at build time; never fetch at UI runtime."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "rust/robrix-ui/resources/fonts/MANIFEST.json"
EXPECTED_NAMES = {"NotoSansSC-Regular.otf", "NotoSansSC-Bold.otf"}
URL_ROOT = "https://raw.githubusercontent.com/notofonts/noto-cjk/523d033d6cb47f4a80c58a35753646f5c3608a78/Sans/SubsetOTF/SC/"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def manifest(path=MANIFEST):
    raw = path.read_bytes()
    value = json.loads(raw)
    assets = value["assets"]
    if (value.get("schema") != "hepta.cjk-fonts.v1"
        or value.get("maxBytes") != 17_000_000
        or len(assets) != 2
        or {a["file"] for a in assets} != EXPECTED_NAMES
        or sum(a["bytes"] for a in assets) > 17_000_000):
        raise ValueError("CJK font inventory/payload cap differs")
    for a in assets:
        if (a["url"] != URL_ROOT + a["file"]
            or a["logical"] != "hepta_robrix_ui/resources/fonts/" + a["file"]
            or not isinstance(a["bytes"], int)
            or not 0 < a["bytes"] <= 17_000_000
            or not re.fullmatch(r"[0-9a-f]{64}", a["sha256"])):
            raise ValueError("Unpinned CJK asset")
    notice = path.parent / "OFL.txt"
    check(notice.read_bytes(), value["license"], "license")
    check((path.parent / "NOTICE.txt").read_bytes(), value["notice"], "notice")
    return value, sha(raw)


def check(data, entry, label):
    if len(data) != entry["bytes"] or sha(data) != entry["sha256"]:
        raise ValueError("CJK resource bytes mismatch: " + label)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".font-", delete=False) as f:
        temporary = Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            f.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def download(entry):
    request = urllib.request.Request(entry["url"], headers={"User-Agent": "Hepta-pinned-font-builder"})
    # This is a per-socket-operation timeout, not a whole-transfer deadline.
    # The allocation/read is independently limited to the exact byte cap + 1.
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.geturl() != entry["url"]:
            raise ValueError("Unexpected CJK font redirect")
        return response.read(entry["bytes"] + 1)


def prepare(cache=None, *, offline=False, install=None):
    value, identity = manifest()
    cache = (cache or Path(os.environ.get("HEPTA_CJK_FONT_CACHE", ROOT / "rust/target/font-assets"))) / identity
    records = []
    for entry in value["assets"]:
        path = cache / entry["file"]
        if path.is_symlink():
            raise ValueError("CJK cache entry must not be a symlink")
        if path.exists():
            if not path.is_file() or path.stat().st_size != entry["bytes"]:
                raise ValueError("CJK resource bytes mismatch: " + entry["file"])
            with path.open("rb") as stream:
                data = stream.read(entry["bytes"] + 1)
            check(data, entry, entry["file"])  # corrupt cache fails; never silently replaced
        else:
            if offline:
                raise ValueError("CJK font missing offline; run tools/prepare-fonts.py first: " + str(path))
            data = download(entry)
            check(data, entry, entry["file"])
            atomic_write(path, data)
        if install is not None:
            destination = install / entry["file"]
            if destination.is_symlink():
                raise ValueError("CJK installation entry must not be a symlink")
            atomic_write(destination, data)
        records.append({**entry, "inputPath": str(path.resolve())})
    return {"manifestSha256": identity, "bytes": sum(a["bytes"] for a in records), "assets": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--install", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.cache, offline=args.offline, install=args.install)))
