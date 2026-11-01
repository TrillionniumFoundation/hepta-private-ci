"""Deterministic, label-blind repair of the original project-name cue.

This changes only distractor identifiers on the already evaluated requests.
It must not be described as an independent new holdout.
"""

import copy
import hashlib
import re


PROJECT_SALT = "hepta-semantic-v14-project-cue-repair-v1"
PROJECT_PREFIX = re.compile(r"^For project (Aurora-[^: ]+): (.*)$", re.DOTALL)


def request_body(text):
    match = PROJECT_PREFIX.fullmatch(text)
    if match is None:
        raise ValueError("Expected the existing project prefix")
    return match.group(2)


def project_for_body(body):
    """Accept semantic text only: no label, row index, or oracle metadata."""
    digest = hashlib.sha256((PROJECT_SALT + "\0" + body).encode("utf-8")).hexdigest()
    return "Aurora-" + digest[:8]


def repair_row(row):
    if row["query"] != row["text"]:
        raise ValueError("The two original request fields must agree")
    body = request_body(row["text"])
    project = project_for_body(body)
    repaired = copy.deepcopy(row)
    repaired["text"] = repaired["query"] = f"For project {project}: {body}"
    repaired["unseen_project"] = project
    return repaired
