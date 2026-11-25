"""Private A/B intake validation; declarations never become human authority."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

SCHEMA = "hepta.adoption-closure.private-intake.v2"
ROLES = ("a_failure", "a_success", "a_train_consent", "a_enrollment",
         "b_evaluate_consent", "b_enrollment", "b_future", "keep",
         "b_use_first", "b_use_again")
HASH_FIELDS = ("study", "parent", "candidate", "freeze", "loop", "runtime_artifacts")
BLOCKER = "ORIGINAL_TURN_VERIFIER_REQUIRED"
BASE_ROLES = {"a_failure", "a_success", "a_train_consent", "a_enrollment", "keep"}
ROLE_GROUPS = (BASE_ROLES, BASE_ROLES | {"b_evaluate_consent", "b_enrollment", "b_future"},
               set(ROLES) - {"b_use_again"}, set(ROLES))
SEQUENCES = ("a_success", "a_authorization", "freeze", "b_first_arrival",
             "b_evaluation", "first_use", "second_use")
STAGES = ("frozen_waiting_b", "evaluation_ready", "first_use_ready", "repeat_use_ready")


class Refused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value)
            and value != "0" * 64, "nonzero SHA-256 required")
    return value


def parse(raw):
    require(len(raw) <= 1024 * 1024, "JSON exceeds intake bound")

    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, "duplicate JSON field")
            out[key] = value
        return out

    def finite(value):
        raise Refused("nonfinite JSON number")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=finite)


def read_json(path):
    with Path(path).open("rb") as source:
        return parse(source.read(1024 * 1024 + 1))


def validate(manifest):
    expected = {"schema", "scope", "pins", "objects", "enrollment", "sequence"}
    require(isinstance(manifest, dict) and set(manifest) == expected, "closed intake schema")
    require(manifest["schema"] == SCHEMA, "intake namespace mismatch")
    require(manifest["scope"] in ("engineering_fixture", "protected_original_owner"), "scope")
    pins = manifest["pins"]
    require(isinstance(pins, dict) and set(pins) == set(HASH_FIELDS), "complete fixed pins")
    for key, value in pins.items():
        if key != "loop" or value is not None:
            digest(value)
    require(pins["parent"] != pins["candidate"], "candidate must differ from parent")
    objects = manifest["objects"]
    require(isinstance(objects, dict) and set(objects) in ROLE_GROUPS, "complete stage role roster")
    stage = ROLE_GROUPS.index(set(objects))
    require((pins["loop"] is None) == (stage == 0), "loop identity is bound at B admission, after freeze")
    for obj in objects.values():
        require(isinstance(obj, dict) and set(obj) == {"sha256", "bytes"}, "content-addressed role")
        digest(obj["sha256"])
        require(type(obj["bytes"]) is int and 0 < obj["bytes"] <= 16 * 1024 * 1024, "object bound")
    # Exact repeats cannot be renamed into a new future task or second use.
    tasks = [objects[r]["sha256"] for r in ("a_failure", "a_success", "b_future",
                                           "keep", "b_use_first", "b_use_again") if r in objects]
    require(len(set(tasks)) == len(tasks), "repeated source/task bytes")
    people = manifest["enrollment"]
    require(isinstance(people, dict) and set(people) == {"authority", "person_a", "person_b"},
            "site person reference contract")
    for key in ("authority", "person_a"):
        digest(people[key])
    if stage:
        digest(people["person_b"])
        require(people["person_a"] != people["person_b"], "one person cannot count twice")
        for left, right in (("a_enrollment", "b_enrollment"),
                            ("a_train_consent", "b_evaluate_consent")):
            require(objects[left]["sha256"] != objects[right]["sha256"], "reissued authority object")
    else:
        require(people["person_b"] is None, "B is not registered before original arrival")
    order = manifest["sequence"]
    names = SEQUENCES[:(3, 5, 6, 7)[stage]]
    require(isinstance(order, dict) and set(order) == set(names), "source sequence contract")
    require(all(type(order[k]) is int and 0 < order[k] < 2**63 for k in names), "source sequence")
    require(all(order[x] < order[y] for x, y in zip(names, names[1:])), "source chronology")
    return manifest


def advance(previous, current):
    """Append a prospective stage without rewriting the candidate or originals."""
    validate(previous); validate(current)
    old_stage = ROLE_GROUPS.index(set(previous["objects"]))
    new_stage = ROLE_GROUPS.index(set(current["objects"]))
    require(new_stage == old_stage + 1, "one forward intake stage required")
    prior_pins = dict(previous["pins"])
    if old_stage == 0:
        prior_pins["loop"] = current["pins"]["loop"]
    require(previous["scope"] == current["scope"] and prior_pins == current["pins"],
            "frozen candidate/runtime/scope cannot change")
    for group in ("objects", "sequence", "enrollment"):
        for key, value in previous[group].items():
            if group == "enrollment" and key == "person_b" and old_stage == 0:
                continue
            require(current[group].get(key) == value, "original intake prefix changed")
    return {**metadata_result(current), "predecessor_intake_sha256": sha(canonical(previous)),
            "immutable_prefix_checked": True}


def metadata_result(manifest):
    validate(manifest)
    # Person references and task hashes stay private: even a digest can expose a
    # small identifying value. Export the complete package commitment only.
    return {
        "schema": "hepta.adoption-closure.intake-preflight.v2",
        "intake_sha256": sha(canonical(manifest)),
        "scope": manifest["scope"], "candidate_sha256": manifest["pins"]["candidate"],
        "role_count": len(manifest["objects"]),
        "intake_stage": STAGES[ROLE_GROUPS.index(set(manifest["objects"]))],
        "structure_checked": True,
        "provenance_authenticated": False, "distinct_people_authenticated": False,
        "original_turn_authorization_verified": False,
        "production_authorization_available": False,
        "authorization_blocker": BLOCKER,
    }


def verify_private_objects(manifest, root):
    """Engineering material check only; owner scope stops before opening root."""
    validate(manifest)
    require(manifest["scope"] == "engineering_fixture", BLOCKER)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    # The trusted operator supplies root. Only digest basenames come from data.
    fd = os.open(root, flags)
    try:
        info = os.fstat(fd)
        require(info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0,
                "private owner directory required")
        for obj in manifest["objects"].values():
            child = os.open(obj["sha256"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=fd)
            with os.fdopen(child, "rb") as stream:
                before = os.fstat(stream.fileno())
                require(stat.S_ISREG(before.st_mode) and before.st_uid == info.st_uid
                        and before.st_mode & 0o077 == 0 and before.st_nlink == 1,
                        "private immutable regular object required")
                require(before.st_size == obj["bytes"], "object byte count mismatch")
                raw = stream.read(obj["bytes"] + 1)
                after = os.fstat(stream.fileno())
                require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                         before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                                after.st_mtime_ns, after.st_ctime_ns), "object changed")
                require(sha(raw) == obj["sha256"], "object content changed")
    finally:
        os.close(fd)
    return {**metadata_result(manifest), "objects_verified": len(manifest["objects"]),
            "human_participants": 0, "model_calls": 0, "training_updates": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--engineering-objects", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    result = (advance(read_json(args.previous), manifest) if args.previous else metadata_result(manifest))
    if args.engineering_objects:
        result.update(verify_private_objects(manifest, args.engineering_objects))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
