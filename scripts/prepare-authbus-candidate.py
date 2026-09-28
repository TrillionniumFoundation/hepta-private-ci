#!/usr/bin/env python3
"""Prepare already-materialized AuthBus source without replaying old migrations.

Only reviewed local dependency edges may be added to Cargo.lock. Registry
versions, sources and checksums remain byte-for-byte unchanged. Formatting and
content-bound maps are committed before the separate --locked native gates.
"""
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, before: str, after: str) -> None:
    target = ROOT / path
    source = target.read_text()
    if source.count(after) == 1 and before not in source.replace(after, "", 1):
        return
    if source.count(before) != 1 or after in source:
        raise SystemExit(f"{path}: unexpected source; refusing an unaudited rewrite")
    target.write_text(source.replace(before, after, 1))


def repair_lock() -> None:
    path = ROOT / "codex-rs/Cargo.lock"
    original = path.read_text()
    before = tomllib.loads(original)
    additions = {
        "codex-hepta-authbus": {"rustix 1.1.4"},
        "codex-hepta-authbus-p1-3-qualification": {
            "ed25519-dalek", "serde_json", "tempfile", "tokio",
        },
        "codex-hepta-evidence": {"codex-hepta-authbus-p1-3-qualification"},
        "codex-hepta-agentd": {"codex-hepta-authbus-p1-3-qualification"},
    }
    packages = before["package"]
    known = {p["name"] for p in packages}
    if sum(p["name"] == "rustix" and p["version"] == "1.1.4" for p in packages) != 1:
        raise SystemExit("reviewed rustix version is absent; do not resolve new dependencies")
    text = original
    for name, edges in additions.items():
        selected = [p for p in packages if p["name"] == name and "source" not in p]
        if len(selected) != 1 or any(e.split()[0] not in known for e in edges):
            raise SystemExit(f"unexpected lock package identity: {name}")
        pattern = re.compile(r'\[\[package\]\]\nname = "' + re.escape(name)
                             + r'"\n.*?(?=\n\[\[package\]\]|\Z)', re.S)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise SystemExit(f"unexpected lock package count: {name}")
        match = matches[0]
        block = match.group()
        old_dependencies = selected[0].get("dependencies", [])
        updated = sorted(set(old_dependencies) | edges)
        replacement = "dependencies = [\n" + "".join(f' "{edge}",\n' for edge in updated) + "]"
        block, count = re.subn(r"dependencies = \[.*?\]", lambda _: replacement, block, count=1, flags=re.S)
        if count != 1:
            raise SystemExit(f"missing dependency list: {name}")
        text = text[:match.start()] + block + text[match.end():]
    after = tomllib.loads(text)
    if len(after["package"]) != len(packages):
        raise SystemExit("unexpected package resolution")
    for old, new in zip(packages, after["package"]):
        expected = dict(old)
        if old["name"] in additions and "source" not in old:
            expected["dependencies"] = sorted(set(old.get("dependencies", [])) | additions[old["name"]])
        if expected != new:
            raise SystemExit("lock repair changed an unreviewed dependency or registry pin")
    path.write_text(text)


def main() -> None:
    required = {
        "codex-rs/hepta-authbus/src/lib.rs": (
            "pub(crate) use authority_store::AuthBusAuthorityStore;", "mod metrics;",
            '#![doc = include_str!("../SEALED_API.md")]',
        ),
        "codex-rs/hepta-authbus/src/host.rs": (
            "\n    _checkpoint_owner_fence: OwnerFence,\n", "\n    _owner_fence: OwnerFence,\n",
        ),
    }
    for path, markers in required.items():
        source = (ROOT / path).read_text()
        for marker in markers:
            if source.count(marker) != 1:
                raise SystemExit(f"{path}: materialized-source prerequisite changed: {marker}")
    replace_once(
        "codex-rs/hepta-agentd/tests/kernel_evidence_product.rs",
        "registry.message_issuer(&claims.issuer_id, claims.key_epoch)?",
        "registry.message_issuer(&message.claims.issuer_id, message.claims.key_epoch)?",
    )
    replace_once(
        "scripts/generate-authbus-implementation-map.py",
        'EXACT = {\n',
        'EXACT = {\n    "codex-rs/hepta-agentd/src/evidence_trust.rs",\n',
    )
    repair_lock()
    print("Reviewed dependency edges and materialized source prepared; native qualification remains required.")


if __name__ == "__main__":
    main()
