"""Relocate a frozen study without overwriting evidence or refreshing source hashes.

This changes only interpreter/root/output locations and mechanically binds
content donors to the new output directory. Model/data/seeds/budgets remain as
preregistered. A rerun is a reproduction, not fresh heldout confirmation.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .study import check_frozen, digest, run, save_new


def relocate(kind, output, python):
    root = Path(__file__).resolve().parents[2]
    ns = Path("experiments/hcsn_mechanism_content_v2")
    source_path = root / ns / "protocols" / (kind + "001") / "plan.json"
    original = json.loads(source_path.read_text())
    check_frozen(root, original["frozen_files"])
    output = Path(output).resolve()
    if not output.is_relative_to(root):
        raise ValueError("Reproduction output must be a new directory inside this checkout")
    output.mkdir(parents=True, exist_ok=False)
    destination = output.relative_to(root)
    old_prefix = str(ns / "results" / (kind + "001") / "jobs")
    new_prefix = str(destination / "jobs")

    def moved(value):
        if value == old_prefix or value.startswith(old_prefix + "/"):
            return new_prefix + value[len(old_prefix):]
        return value

    jobs, templates = [], []
    for job in original["jobs"]:
        relocated = {**job, "argv": [str(python), *[moved(arg) for arg in job["argv"][1:]]],
                     "outputs": [moved(path) for path in job.get("outputs", [])]}
        if "--template" in relocated["argv"]:
            position = relocated["argv"].index("--template") + 1
            source_template = root / relocated["argv"][position]
            template = json.loads(source_template.read_text())
            if "pretrained_from" in template:
                template["pretrained_from"] = moved(template["pretrained_from"])
            new_template = destination / "templates" / source_template.name
            save_new(root / new_template, template)
            relocated["argv"][position] = str(new_template)
            templates.append(dict(path=str(new_template), sha256=digest(root / new_template)))
        jobs.append(relocated)
    old_templates = str(ns / "protocols" / (kind + "001") / "jobs") + "/"
    frozen = [row for row in original["frozen_files"] if not row["path"].startswith(old_templates)]
    plan = {**original, "repository_root": str(root), "jobs": jobs, "frozen_files": frozen + templates,
            "reproduction": {"source_plan_sha256": digest(source_path),
                "relocated_at_utc": datetime.now(timezone.utc).isoformat(),
                "changed_fields": ["interpreter", "repository_root", "output paths", "donor paths"],
                "fresh_confirmation": False}}
    save_new(output / "plan.json", plan)
    check_frozen(root, plan["frozen_files"])
    return output / "plan.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["mechanism", "content"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    plan = relocate(args.kind, args.output, args.python)
    print(json.dumps({"plan": str(plan), "sha256": digest(plan), "run_requested": args.run}), flush=True)
    if args.run:
        result = run(plan, args.output / "meter", jobs=2)
        raise SystemExit(bool(result["failures"]))
