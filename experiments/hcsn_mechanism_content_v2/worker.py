"""Resolve a preregistered content job's dependency by exact checkpoint identity."""

import argparse
import json
from pathlib import Path

from .content_train import file_hash, run


def resolve(template):
    job = json.loads(Path(template).read_text())
    job["template_sha256"] = file_hash(template)
    dependency = job.pop("pretrained_from", None)
    if dependency:
        directory = Path(dependency)
        checkpoint = directory / "selected.pt"
        selection = json.loads((directory / "selection.json").read_text())
        source_job = json.loads((directory / "job.json").read_text())
        sha = file_hash(checkpoint)
        if sha != selection["selected_checkpoint_sha256"]:
            raise ValueError("Shared donor checkpoint differs from its selection receipt")
        if source_job["family"] != "shared" or source_job["task"] != job["task"]:
            raise ValueError("Shared donor task/family mismatch")
        if source_job["seed"] != job["seed"]:
            raise ValueError("The predeclared paired seed must share one donor")
        job.update(pretrained=str(checkpoint), pretrained_sha256=sha,
                   pretrained_selection_sha256=file_hash(directory / "selection.json"),
                   pretrained_job_sha256=file_hash(directory / "job.json"),
                   pretrained_binding_rule="selected.pt hash equals completed dependency selection")
    return job


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-test", action="store_true")
    args = parser.parse_args()
    summary = run(resolve(args.template), args.output, allow_test=args.allow_test)
    print(json.dumps({"completed": summary["completed"], "selected_step": summary["selected_step"],
                      "costs": summary["costs"]}))
