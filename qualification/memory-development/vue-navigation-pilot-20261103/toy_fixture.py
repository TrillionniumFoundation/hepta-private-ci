"""Generate invented raw-Markdown fixtures only, never download or read real data."""
import argparse
import hashlib
from pathlib import Path

from runner import sha256, write_json


def create(root: Path, freeze: Path):
    root.mkdir(parents=True, exist_ok=False)
    files = []
    texts = [
        "# Alpha entry {#entry}\nAlpha alpha route. [Mandatory condition](./toy-2.md#target)\n",
        "# Alpha second {#second}\nAlpha route. [Second prerequisite](./toy-3.md#prerequisite)\n",
        "# Target {#target}\nAn invented prerequisite needs a blue lever.\n",
        "# Prerequisite {#prerequisite}\nThe invented lever must be held while moving.\n",
        "# Filler four {#four}\nAlpha unrelated material.\n",
        "# Filler five {#five}\nAlpha unrelated example.\n",
        "# Unicode {#unicode}\nToy naïve café 汉字 content remains raw.\n",
        "# Code {#code}\n```text\nA toy code example, inert.\n```\n",
    ]
    for i, text in enumerate(texts):
        body = text.encode("utf-8")
        local = f"toy-{i}.md"
        (root / local).write_bytes(body)
        files.append({"source": "self-authored-toy", "path": f"src/guide/{local}",
                      "local_path": local, "sha256": hashlib.sha256(body).hexdigest(),
                      "git_blob_sha1": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()})
    manifest = root / "manifest.json"
    queries = root / "queries.json"
    write_json(manifest, {"fixture_kind": "self_authored_synthetic", "commit": "0" * 40, "repository": "example/synthetic-docs", "files": files})
    write_json(queries, [{"id": f"toy-{i}", "question": query} for i, query in enumerate([
        "alpha route mandatory condition", "invented lever prerequisite", "naïve café 汉字"] )])
    write_json(root / "authorization.json", {"kind": "synthetic_engineering_only",
               "manifest_sha256": sha256(manifest), "queries_sha256": sha256(queries),
               "freeze_sha256": sha256(freeze)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    args = parser.parse_args()
    create(args.output, args.freeze)
