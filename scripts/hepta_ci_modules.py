"""Read module ownership and risk from exact Git trees, including the V8 base.

No candidate code is executed and no mutable worktree or second registry is
consulted. Old and new declarations must both participate in impact/risk so a
candidate cannot lower its own classification by deleting or weakening a row.
"""

import json
import re
import subprocess
import tomllib
from pathlib import Path

MANIFEST = re.compile(r"docs/modules/([a-z0-9_.-]+)/module\.toml\Z")
OID = re.compile(r"[0-9a-f]{40}\Z")
READ_ONLY_STATES = frozenset(
    {
        "stateless",
        "stateless_runtime",
        "ephemeral",
        "ephemeral_isolated",
        "read_only",
        "read_only_remote",
    }
)
STATEFUL_STATES = frozenset(
    {
        "stateful",
        "stateful_projection",
        "stateful_rebuildable",
        "stateful_append_only",
        "stateful_shadow",
        "stateful_create_only",
        "isolated_stateful",
        "stateful_external",
    }
)
# Presentation fields have no authority or runtime meaning. Anything unknown
# remains semantic, rather than acquiring a lightweight path by default.
PRESENTATION_FIELDS = frozenset(
    {"order", "technicalDocument", "sourceInterpretation", "documentationReady"}
)
AUTHORITY_FIELDS = frozenset(
    {
        "owner",
        "writes",
        "denies",
        "hotPathPolicy",
        "publicSurfacePolicy",
        "localHotPathCentralRpc",
    }
)
RISK_ORDER = {"ordinary": 0, "stateful": 1, "effect": 2, "release": 3}


def load_catalog(
    root: Path, revision: str, paths: set[str] | None = None
) -> dict[str, dict]:
    if not OID.fullmatch(revision):
        raise ValueError("module inputs require an exact Git SHA")
    command = ["git", "--no-replace-objects", "-C", str(root)]
    if paths is None:
        paths = set(
            subprocess.check_output(
                command + ["ls-tree", "-r", "--name-only", "-z", revision]
            )
            .decode("utf-8")
            .split("\0")
        )
    names = sorted(path for path in paths if MANIFEST.fullmatch(path))
    legacy = not names
    if legacy and "docs/modules/registry.toml" in paths:
        raise ValueError("canonical module registry has no module manifests")
    if legacy:
        names = [
            p
            for p in ("docs/modules/MODULES.json", "docs/modules/CARGO_BINDINGS.json")
            if p in paths
        ]
        if not names:
            return {}
    result = subprocess.run(
        command + ["cat-file", "--batch"],
        input="".join(f"{revision}:{path}\n" for path in names).encode(),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    documents = {}
    offset = 0
    for path in names:
        end = result.index(b"\n", offset)
        header = result[offset:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError(f"module input is not a blob: {path}")
        size = int(header[2])
        offset = end + 1
        payload = result[offset : offset + size].decode("utf-8")
        offset += size + 1
        documents[path] = json.loads(payload) if legacy else tomllib.loads(payload)
    if legacy:
        rows = documents.get("docs/modules/MODULES.json", {}).get("modules", [])
        bindings = documents.get("docs/modules/CARGO_BINDINGS.json", {}).get(
            "bindings", []
        )
        documents = {}
        for row in rows:
            row = dict(row)
            row["cargoPackages"] = [
                {"path": b["packagePath"]} for b in bindings if b["module"] == row["id"]
            ]
            documents[f"docs/modules/{row['id']}/module.toml"] = row
    seen_roots = {}
    for path, row in documents.items():
        match = MANIFEST.fullmatch(path)
        if not isinstance(row, dict):
            raise ValueError(f"invalid module object: {path}")
        if not legacy and row.get("schema") != "hepta.module-manifest.v1":
            raise ValueError(f"unsupported module schema: {path}")
        if not match or row.get("id") != match[1]:
            raise ValueError(f"module identity does not match path: {path}")
        if (
            not isinstance(row.get("state"), str)
            or row["state"] not in READ_ONLY_STATES | STATEFUL_STATES
        ):
            raise ValueError(f"unknown module state: {path}")
        owner, writes = row.get("owner"), row.get("writes")
        if (
            not isinstance(owner, str)
            or not owner
            or owner.strip() != owner
            or not isinstance(writes, list)
            or any(
                not isinstance(domain, str) or not domain or domain.strip() != domain
                for domain in writes
            )
            or len(writes) != len(set(writes))
        ):
            raise ValueError(f"invalid module authority: {path}")
        packages = row.get("cargoPackages", [])
        if not isinstance(packages, list):
            raise ValueError(f"invalid module packages: {path}")
        for package in packages:
            folder = package.get("path") if isinstance(package, dict) else None
            if (
                not isinstance(folder, str)
                or not folder.startswith("codex-rs/")
                or any(p in {"", ".", ".."} for p in folder.split("/"))
                or "\\" in folder
            ):
                raise ValueError(f"invalid module package path: {path}")
            if folder in seen_roots:
                raise ValueError(f"duplicate module package ownership: {folder}")
            seen_roots[folder] = row["id"]
    return documents


def module_risk(row: dict) -> str:
    # Privileged control domains and externally stateful owners retain the
    # effect boundary independently of CI functional group labels.
    if (
        row["id"].startswith(("kernel.", "auth.", "secrets."))
        or row["id"]
        in {
            "runtime.supervisor",
            "control.engineering",
            "browser.servo",
            "channel.matrix",
            "automation.taskflow",
            "inference.worker",
            "inference.control",
            "platform.types",
            "platform.wire",
            "runtime.agentd",
            "runtime.codex",
            "control.runtime",
        }
        or row["state"] == "stateful_external"
    ):
        return "effect"
    if row["state"] in STATEFUL_STATES or row["writes"]:
        return "stateful"
    return "ordinary"


def manifest_risk(before: dict | None, after: dict | None) -> str:
    if before is not None and after is not None:
        changed = {
            key
            for key in before.keys() | after.keys()
            if before.get(key) != after.get(key)
        }
        if changed <= PRESENTATION_FIELDS:
            return "ordinary"
        if changed & AUTHORITY_FIELDS:
            return "effect"
        # Existing interface/ownership graph changes require lifecycle checks;
        # unknown keys cannot silently become presentation-only fields.
        if changed:
            return max(
                ("stateful", module_risk(before), module_risk(after)),
                key=RISK_ORDER.get,
            )
    risk = max(
        (module_risk(row) for row in (before, after) if row is not None),
        key=RISK_ORDER.get,
    )
    # Removing a provider must still prove dependency-safe retirement, even
    # when its own implementation was read-only.
    if after is None and risk == "ordinary":
        return "stateful"
    return risk


def assess_changes(
    root: Path, paths: list[str], base: str, head: str
) -> tuple[str, list[str]]:
    after = load_catalog(root, head)
    try:
        before = load_catalog(root, base)
    except (ValueError, subprocess.CalledProcessError, tomllib.TOMLDecodeError):
        return "effect", ["base module graph unavailable; conservative effect boundary"]
    risks = []
    reasons = []
    for path in paths:
        if MANIFEST.fullmatch(path):
            old, new = before.get(path), after.get(path)
            if old is None and new is None:
                raise ValueError(
                    f"changed manifest absent from both exact trees: {path}"
                )
            risk = manifest_risk(old, new)
        elif path.startswith(".github/workflows/") and any(
            word in path.rsplit("/", 1)[-1]
            for word in ("release", "deploy", "publish", "signing")
        ):
            risk = "release"
        elif (
            path.startswith("docs/")
            and path.endswith(".md")
            or path in {"README.md", "CONTRIBUTING.md"}
        ):
            risk = "ordinary"
        else:
            matched = []
            for catalog in (before, after):
                owners = [
                    (len(package["path"]), row)
                    for row in catalog.values()
                    for package in row.get("cargoPackages", [])
                    if path.startswith(package["path"] + "/")
                ]
                if owners:
                    matched.append(max(owners, key=lambda value: value[0])[1])
            risk = (
                max((module_risk(row) for row in matched), key=RISK_ORDER.get)
                if matched
                else "effect"
            )
            if path.endswith("/build.rs"):
                risk = "effect"
            elif path.endswith("/Cargo.toml"):
                risk = max((risk, "stateful"), key=RISK_ORDER.get)
        risks.append(risk)
        reasons.append(f"{risk}: {path}")
    return max(risks, key=RISK_ORDER.get, default="ordinary"), reasons
