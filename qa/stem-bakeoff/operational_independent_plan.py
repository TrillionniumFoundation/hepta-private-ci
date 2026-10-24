"""Audit prior source exposure and freeze source-only acquisition for 48 new bugs.

This module never executes benchmark tests and never reads their outcome files.
The acquisition plan does not authorize evaluation; the governing task/runtime
protocol and prepared candidate actions must be frozen separately.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from operational_cohort_plan import canonical, command_specs, decode, digest, properties

PROJECTS = {"ansible": 18, "fastapi": 16, "httpie": 5, "sanic": 5, "cookiecutter": 4}
DEVELOPMENT = {"train": ["youtube-dl", "scrapy"], "tuning": ["luigi"],
               "calibration": ["thefuck", "tqdm", "PySnooper"]}
ADAPTER = "cookiecutter-tox-selector-to-explicit-pytest-v1"


def file_record(path):
    raw = Path(path).read_bytes()
    return {"path": str(Path(path).resolve()), "sha256": digest(raw), "bytes": len(raw)}


def repository(value):
    value = value.removeprefix("https://github.com/").rstrip("/").removesuffix(".git").lower()
    if re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", value) is None:
        raise ValueError("explicit GitHub repository identity required")
    return value


def normalize_commands(project, raw):
    commands = []
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        words = shlex.split(line)
        adapter = None
        if words[0] == "tox":
            if project != "cookiecutter" or len(words) < 2 or any(w.startswith("-") for w in words[1:]):
                raise ValueError("only the declared Cookiecutter tox-selector adapter is permitted")
            effective, adapter = "pytest " + shlex.join(words[1:]), ADAPTER
        else:
            effective = line
        spec, = command_specs(effective)
        commands.append({**spec, "upstream_original": line, "source_adapter": adapter})
    if not commands:
        raise ValueError("empty declared command list")
    return commands


def exposure(old_protocol, datasets, study_registry):
    prior = json.loads(Path(old_protocol).read_bytes())
    if prior.get("schema") != "hepta.operational-cohort-protocol.v1":
        raise ValueError("prior operational source protocol required")
    groups = {b["group_id"] for b in prior["bugs"]}
    revisions = {v for b in prior["bugs"] for v in b["revisions"].values()}
    repos = {repository(v["url"]) for v in prior["projects"].values()}
    project_names = {name.lower() for name in prior["projects"]}
    records, dataset_records = [file_record(old_protocol), file_record(study_registry)], []
    registry = json.loads(Path(study_registry).read_bytes())
    if not registry.get("all_registered_main_studies_complete"):
        raise ValueError("complete prior experimental registry required")
    study_datasets = {row["dataset"]: row["dataset_sha256"] for row in registry["main_studies"]}
    paths = sorted(set(map(str, datasets)) | set(study_datasets))
    for name in paths:
        path = Path(name)
        record = file_record(path)
        if name in study_datasets and record["sha256"] != study_datasets[name]:
            raise ValueError("prior study dataset changed")
        data = json.loads(path.read_bytes())
        counts = Counter()
        for row in data["rows"]:
            version = row.get("source_version", {})
            version = version if isinstance(version, dict) else {}
            repo = version.get("repo")
            if repo is not None:
                repo = repository(repo)
            elif row.get("repo") in prior["projects"]:
                repo = repository(prior["projects"][row["repo"]]["url"])
            elif row.get("repo"):
                if "/" in row["repo"]:
                    repo = repository(row["repo"])
                else:
                    project_names.add(row["repo"].lower())
            if repo is not None:
                repos.add(repo)
                project_names.add(repo.split("/")[-1])
                counts[(repo, row["split"])] += 1
            if str(row.get("group_id", "")).startswith("bugsinpy/"):
                groups.add(row["group_id"])
            for key in ("base_commit", "candidate_commit"):
                if key in version:
                    revisions.add(version[key])
        dataset_records.append({**record, "rows": len(data["rows"]),
            "repository_split_rows": [{"repository": r, "split": s, "rows": n}
                                      for (r, s), n in sorted(counts.items())]})
    development = {role: sorted(b["group_id"] for b in prior["bugs"] if b["project"] in names)
                   for role, names in DEVELOPMENT.items()}
    if {role: len(ids) for role, ids in development.items()} != {"train": 83, "tuning": 33, "calibration": 44}:
        raise ValueError("prior development source inventory differs from the frozen role assignment")
    return {"records": records, "datasets": dataset_records, "repositories": sorted(repos), "project_names": sorted(project_names),
            "operational_group_ids": sorted(groups), "source_revisions": sorted(revisions),
            "development_groups": development, "excluded_prior_holdout_projects": ["black", "tornado"],
            "exposure_scope": "All prior operational protocol groups plus repository-bearing rows from the registered experiments and explicitly supplied older datasets; no model outcomes or quality scores used."}


def build(root, old_protocol, datasets, study_registry):
    root = Path(root)
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    prior = exposure(old_protocol, datasets, study_registry)
    blobs = {}
    for line in subprocess.check_output(["git", "-C", str(root), "ls-tree", "-r", "HEAD", "projects"], text=True).splitlines():
        metadata, path = line.split("\t", 1)
        blobs[path] = metadata.split()[2]
    catalog = {p.name: len(list(p.glob("bugs/*/bug.info"))) for p in sorted((root / "projects").iterdir()) if p.is_dir()}
    projects, bugs, inventory = {}, [], []
    for project, expected_count in PROJECTS.items():
        directory = root / "projects" / project
        origin = properties(directory / "project.info")["github_url"]
        repo = repository(origin)
        if repo in prior["repositories"] or project.lower() in prior["project_names"] or repo.split("/")[-1] in prior["project_names"]:
            raise ValueError("proposed independent project is already experimentally exposed: " + project)
        projects[project] = {"url": "https://github.com/" + origin.removeprefix("https://github.com/").rstrip("/"),
                             "original_metadata_url": origin, "split": "holdout"}
        folders = sorted((p for p in (directory / "bugs").iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name))
        if len(folders) != expected_count:
            raise ValueError("candidate pool changed before acquisition")
        for folder in folders:
            info = properties(folder / "bug.info")
            revisions = {role: info[key] for role, key in (("base", "buggy_commit_id"), ("candidate", "fixed_commit_id"))}
            if any(re.fullmatch(r"[0-9a-f]{40}", v) is None for v in revisions.values()):
                raise ValueError("full pinned revisions required")
            group = "bugsinpy/" + project + "/" + folder.name
            if group in prior["operational_group_ids"] or set(revisions.values()).intersection(prior["source_revisions"]):
                raise ValueError("candidate group or source revision was exposed previously")
            records = {}
            for path in [directory / "project.info", *[folder / name for name in ("bug.info", "run_test.sh", "requirements.txt", "bug_patch.txt", "setup.sh") if (folder / name).is_file()]]:
                raw, relative = path.read_bytes(), path.relative_to(root).as_posix()
                blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                if blobs.get(relative) != blob:
                    raise ValueError("metadata bytes differ from the pinned upstream Git commit")
                item = {**file_record(path), "upstream_path": relative, "git_blob": blob}
                inventory.append(item)
                if path.parent == folder:
                    records[path.name] = {k: item[k] for k in ("bytes", "sha256")}
            tests = info["test_file"].split(";")
            if any(not p or p.startswith("/") or ".." in Path(p).parts for p in tests):
                raise ValueError("invalid declared test path")
            bugs.append({"group_id": group, "project": project, "bug_id": int(folder.name), "split": "holdout",
                "revisions": revisions, "test_files": tests, "upstream_python": info.get("python_version"),
                "declared_pythonpath": info.get("pythonpath"), "commands": normalize_commands(project, decode(folder / "run_test.sh")),
                "metadata_files": records})
    pairs = {(b["project"], *b["revisions"].values()) for b in bugs}
    if len(pairs) != len(bugs):
        raise ValueError("duplicate source pair cannot count as another independent bug group")
    plan = {"schema": "hepta.independent-operational-source-plan.v1", "upstream": {"repository": "https://github.com/soarsmu/BugsInPy", "commit": commit},
        "projects": projects, "bugs": bugs, "development_projects": DEVELOPMENT,
        "execution_policy": {"acquired_artifact_byte_limit": 750000000, "benchmark_execution_authorized_by_this_file": False},
        "candidate_policy": "Retain every declared primary line plus up to three deterministic same-file comparators per line; deduplicate exact runner and args per bug before outcomes.",
        "holdout_policy": "All 48 groups retain external holdout membership regardless of preparation or runtime availability; unavailable cases remain in coverage denominators.",
        "command_adapter": {"id": ADAPTER, "scope": "Only Cookiecutter tox-selector declarations become explicit pytest invocations; original lines retained, no implicit tox hooks."},
        "not_yet_frozen": ["governing prospective task protocol", "dependency runtimes", "actual prepared action inventory"],
        "source_code_sha256": {Path(__file__).name: digest(Path(__file__).read_bytes())}}
    audit = {"schema": "hepta.independent-operational-exposure-audit.v1", "prior_exposure": prior,
        "catalog_project_group_counts": catalog, "catalog_total_groups": sum(catalog.values()),
        "selected_project_group_counts": PROJECTS, "selected_groups": len(bugs), "declared_primary_lines": sum(len(b["commands"]) for b in bugs),
        "unique_revision_pairs": len(pairs), "unique_fixed_revisions": len({b["revisions"]["candidate"] for b in bugs}),
        "unique_patch_digests": len({b["metadata_files"]["bug_patch.txt"]["sha256"] for b in bugs}),
        "pinned_project_revisions": sum(len({v for b in bugs if b["project"] == p for v in b["revisions"].values()}) for p in PROJECTS),
        "new_groups_or_revisions_exposed_previously": [],
        "pretrained_corpus_contamination_controlled": False, "new_benchmark_commands_executed": 0,
        "new_benchmark_outcomes_read": 0, "not_an_absolute_absence_claim": "Audit is bounded to the pinned local experimental registries and source datasets listed above; metadata inspection is disclosed and is not model fitting or observed command outcome access."}
    return plan, audit, {x["upstream_path"]: x for x in inventory}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bugsinpy", required=True)
    parser.add_argument("--old-protocol", required=True)
    parser.add_argument("--prior-dataset", action="append", default=[])
    parser.add_argument("--prior-study-registry", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    plan, audit, inventory = build(args.bugsinpy, args.old_protocol, args.prior_dataset, args.prior_study_registry)
    plan["exposure_audit_sha256"] = digest(canonical(audit))
    plan["metadata_inventory_sha256"] = digest(canonical(inventory))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("source-plan.json", plan), ("exposure-audit.json", audit), ("metadata-inventory.json", inventory)):
        (output / name).write_bytes(canonical(value))
    print(json.dumps({"output": str(output), "groups": len(plan["bugs"]), "primary_lines": audit["declared_primary_lines"],
                      "source_plan_sha256": digest(canonical(plan)), "audit_sha256": digest(canonical(audit))}))


if __name__ == "__main__":
    main()
