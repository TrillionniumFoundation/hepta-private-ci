"""Prepare secret, random, pre-task MemoryCell answer commitments.

Only consumes independently supplied exact labels. It cannot authenticate the
reviewer, infer answers, or certify that GitHub received the public plan before
future task exposure. Never print, upload, or feed the private labels to a reader.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets

from factorial_evidence_gate import validate_plan
from memory_trial_admission import bound_read, ensure, utc
from memory_trial_independent_score import ANSWER, COMMITMENT_SCHEME, _answer, commit_identifier


def freeze(template, reviews, *, now=None, nonce_factory=None):
    """Separate a public plan from protected nonce/answer records before use."""
    now = datetime.now(timezone.utc) if now is None else now
    ensure(now.tzinfo is not None and now.utcoffset().total_seconds() == 0,
           "UTC clock required")
    nonce_factory = secrets.token_hex if nonce_factory is None else nonce_factory
    ensure(isinstance(template, dict) and isinstance(reviews, list),
           "template and protected review array required")
    ensure(template.get("schema") == "hepta.memory-factorial.plan.v1"
           and template.get("registered_before_exposure") is True,
           "pre-task registered factorial template required")
    ensure(template.get("answer_commitment_scheme") in (None, COMMITMENT_SCHEME),
           "existing or alien gold commitment scheme rejected")
    cutoff = utc(template.get("cutoff"))
    ensure(cutoff <= now, "future preregistration cutoff is unverifiable")
    cases = template.get("cases")
    ensure(isinstance(cases, list) and cases, "missing source cases")
    ids = set()
    for c in cases:
        ensure(isinstance(c, dict) and isinstance(c.get("id"), str)
               and c["id"] and c["id"] not in ids, "duplicate preregistered cases")
        ids.add(c["id"])
        ensure(c.get("answer_sha256") is None,
               "refuse to replace already committed gold")
        ensure(now < utc(c.get("task_revealed_at")),
               "task already exposed before label freeze")
        ensure(now >= utc(c.get("write_completed_at")),
               "source write not complete before freeze")
    protected, seen = {}, set()
    for review in reviews:
        ensure(isinstance(review, dict) and set(review) == {"id", "expected"},
               "unexpected reviewer payload")
        cid, expected = review["id"], review["expected"]
        ensure(isinstance(cid, str) and cid in ids and cid not in seen,
               "duplicate or unexpected review case")
        ensure(isinstance(expected, str) and ANSWER.fullmatch(expected) is not None
               and _answer(expected) == expected and len(expected.encode()) <= 128,
               "review answer not an exact protocol identifier")
        seen.add(cid)
        nonce = nonce_factory(32)
        ensure(isinstance(nonce, str) and len(nonce) == 64 and nonce != "0" * 64
               and nonce not in {r["nonce"] for r in protected.values()},
               "random independent answer nonces required")
        commitment = commit_identifier(expected, nonce)
        protected[cid] = {"id": cid, "expected": expected, "nonce": nonce,
                          "commitment": commitment}
    ensure(seen == ids, "incomplete protected reviewer census")
    # Copy through JSON rather than sharing nested objects, without touching
    # the caller's frozen template or populating public answer strings.
    public = json.loads(json.dumps(template, ensure_ascii=False, allow_nan=False))
    public["answer_commitment_scheme"] = COMMITMENT_SCHEME
    for c in public["cases"]:
        c["answer_sha256"] = protected[c["id"]]["commitment"]
    validate_plan(public)
    labels = [{k: protected[c["id"]][k] for k in ("id", "expected", "nonce")}
              for c in public["cases"]]
    return public, labels


def dump_exclusive(path, payload):
    path = Path(path)
    ensure(not path.is_symlink() and path.parent.is_dir()
           and not any(part.is_symlink() for part in path.parents),
           "regular destination directory required")
    data = (json.dumps(payload, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as dest:
        dest.write(data)
        dest.flush()
        os.fsync(dest.fileno())
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("template", "reviews", "public-plan", "protected-labels"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--template-sha256", required=True)
    parser.add_argument("--reviews-sha256", required=True)
    args = parser.parse_args()
    ensure(args.public_plan != args.protected_labels and not args.public_plan.exists()
           and not args.protected_labels.exists(),
           "refuse to overwrite either sealed output")
    source = bound_read(args.template, args.template_sha256)
    private_input = bound_read(args.reviews, args.reviews_sha256)
    public, protected = freeze(source, private_input)
    plan_hash = dump_exclusive(args.public_plan, public)
    label_hash = dump_exclusive(args.protected_labels, protected)
    # Never print protected answers, salts, or source review contents.
    print(json.dumps({"public_plan_sha256": plan_hash,
                      "protected_label_file_sha256": label_hash,
                      "case_count": len(protected),
                      "human_reviewer_authentication": False,
                      "production_accepted": False}, sort_keys=True))


if __name__ == "__main__":
    main()