"""Read exactly three pinned metadata files; emit source/split/exposure fields only."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

PINS = {
    "catalog": {"path": "/home/qq/ndu-real-materials-20261107-audit-bffe40c2/pilot-catalog.json", "bytes": 1410133, "sha256": "8433d0c026b0818f8e60ee2f0ae7e7b57c57ae35cbb72cf212b89895b97d0904"},
    "exposure": {"path": "/home/qq/ndu-real-materials-20261107-audit-bffe40c2/public-source-exposure-20261107-v3.json", "bytes": 3231, "sha256": "6722edfc88e1089bcaf0fba9727c233416830fdc6682b461422d26bdfd4cb6af"},
    "baseline_plan": {"path": "/home/qq/mem-candidate-retention-20261109-a6b21bc7/run-002/PLAN.json", "bytes": 172323, "sha256": "488639ca2bd2b25d5c90c77b3adaf58bd8133932bb2cb1bf70fc547447d187d5"},
}
REGISTRY = "09d5f57c5c4c5f421f16c51febd048b7746d5d52723d825240f8655bf7fbdd07"
FAMILIES = {"continuation_not_worthwhile", "preparation_required", "selective_refinement", "text_image_complementary", "text_sufficient"}
ALLOWED_ROLES = {"train", "development", "retention_validation"}
REQUEST_ID = "mem-next-source-inventory-ed353817-20261111-v1"

def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result

def sid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", value):
        raise ValueError("invalid source-group metadata identity")
    return value

def bounded_identity(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ValueError("invalid bounded catalog identity")
    return value

def version(value):
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]

def read_pin(pin):
    path = Path(pin["path"])
    for parent in path.parents:
        mode = parent.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError("metadata parent is not an ordinary directory")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("metadata is not a single-link regular file")
        if before.st_size != pin["bytes"]:
            raise ValueError("metadata size differs from frozen pin")
        chunks = []
        remaining = pin["bytes"] + 1
        while remaining:
            piece = os.read(fd, min(65536, remaining))
            if not piece:
                break
            chunks.append(piece)
            remaining -= len(piece)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        named = path.stat(follow_symlinks=False)
        if version(before) != version(after) or version(named) != version(after):
            raise ValueError("metadata changed while reading")
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != pin["bytes"] or digest != pin["sha256"]:
            raise ValueError("metadata bytes differ from frozen pin")
        data = json.loads(raw, object_pairs_hook=strict_pairs)
        return data, {**pin, "version": version(after), "verified": True}
    finally:
        os.close(fd)

def project_catalog(catalog):
    if set(catalog) != {"cases"} or not isinstance(catalog["cases"], list):
        raise ValueError("unexpected catalog schema")
    ids, roles, episode_owner = set(), {}, {}
    groups = defaultdict(lambda: defaultdict(dict))
    for case in catalog["cases"]:
        if set(case) != {"id", "source_id", "role", "task_family", "packet", "reference", "episode_group"}:
            raise ValueError("unexpected catalog fields")
        source = sid(case["source_id"])
        case_id = bounded_identity(case["id"])
        episode = bounded_identity(case["episode_group"])
        role, family = case["role"], case["task_family"]
        if role not in ALLOWED_ROLES or family not in FAMILIES:
            raise ValueError("unreleased catalog role or unknown family")
        if case_id in ids or roles.setdefault(source, role) != role:
            raise ValueError("duplicate case or source crossing roles")
        if episode_owner.setdefault(episode, (source, role)) != (source, role):
            raise ValueError("episode crosses source or role")
        if family in groups[source][episode]:
            raise ValueError("duplicate source/episode/family")
        ids.add(case_id)
        groups[source][episode][family] = True
    projected = []
    for source in sorted(groups):
        role = roles[source]
        episodes = groups[source]
        required = FAMILIES if role == "development" else {"text_image_complementary"}
        projected.append({
            "source_group_id": source, "role": role,
            "case_count": sum(len(families) for families in episodes.values()),
            "episode_group_count": len(episodes),
            "task_family_counts": dict(sorted(Counter(family for families in episodes.values() for family in families).items())),
            "complete_episode_count_for_existing_released_role": None if role == "train" else sum(required <= families.keys() for families in episodes.values()),
        })
    return {"case_count": len(ids), "source_group_count": len(projected), "roles": dict(sorted(Counter(roles.values()).items())), "groups": projected}

result = {
    "schema": "hepta.mem.next-source-inventory-readonly.v1",
    "request_id": REQUEST_ID,
    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    "host": "ai395", "registry_sha256": REGISTRY, "status": "UNKNOWN",
    "model_calls": 0, "actor_executions": 0, "reference_content_files_opened": 0,
    "metadata_source": "exact original pins; no refreshed global exposure certification",
    "source_identity_created": False, "bindings": {}, "errors": [],
}
documents = {}
for name, pin in PINS.items():
    try:
        documents[name], result["bindings"][name] = read_pin(pin)
    except Exception as error:
        result["errors"].append({"input": name, "type": type(error).__name__, "message": str(error)})
try:
    if "catalog" in documents:
        result["catalog"] = project_catalog(documents["catalog"])
    if "exposure" in documents:
        exposure = documents["exposure"]
        if exposure.get("schema") != "ndu.real.researcher-exposure.v1" or exposure.get("registry_sha256") != REGISTRY:
            raise ValueError("exposure ledger schema or registry differs")
        quarantined = exposure["quarantined_source_groups"]
        if not isinstance(quarantined, list) or len(set(quarantined)) != len(quarantined):
            raise ValueError("invalid exposure source roster")
        result["exposure"] = {"schema": exposure["schema"], "registry_sha256": exposure["registry_sha256"], "quarantined_source_groups": sorted(sid(x) for x in quarantined)}
    if "baseline_plan" in documents:
        plan = documents["baseline_plan"]
        if plan.get("registry_sha256") != REGISTRY or plan.get("catalog") != {key: value for key, value in PINS["catalog"].items() if key != "path"} | {"path": "pilot-catalog.json"}:
            raise ValueError("baseline plan registry/catalog differs")
        source_roles = {}
        for row in plan["episodes"]:
            source, role = sid(row["source_group_id"]), row["split"]
            if role not in ALLOWED_ROLES or source_roles.setdefault(source, role) != role:
                raise ValueError("baseline source crosses roles")
        result["baseline_plan"] = {
            "schema": plan["schema"], "registry_sha256": plan["registry_sha256"],
            "episode_count": len(plan["episodes"]),
            "sources": [{"source_group_id": source, "role": role} for source, role in sorted(source_roles.items())],
            "excluded_source_groups": sorted(sid(x) for x in plan["excluded_source_groups"]),
        }
    if not result["errors"] and set(result["bindings"]) == set(PINS):
        result["status"] = "PINNED_METADATA_VERIFIED_GLOBAL_EXPOSURE_NOT_CERTIFIED"
except Exception as error:
    result["errors"].append({"input": "metadata_projection", "type": type(error).__name__, "message": str(error)})
print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
raise SystemExit(0 if result["status"].startswith("PINNED_") else 2)
