"""The exact fresh grid advances only after its preceding immutable ACK."""

import copy

from .process import EPISODE, checked, read, require

ORDER = [
    "A-17",
    "A-29",
    "A-43",
    "C",
    "B-17",
    "B-29",
    "B-43",
    "W",
    "R-17",
    "R-29",
    "R-43",
    "A_endpoint",
    "B_endpoint",
    "C_endpoint",
]
LABELS = ORDER + ["controller", "analysis", "final_closure"]


def canonical(value, count):
    require(
        value.get("schema") == "hepta.fullstudy.queue.2"
        and value.get("attempt_id") == "attempt02",
        "Original queue schema or compatibility attempt differs",
    )
    require(
        count in (4, 11, 14) and [job["id"] for job in value["jobs"]] == ORDER[:count],
        "Canonical grid order differs",
    )
    for index, job in enumerate(value["jobs"]):
        deps = job.get("requires", [])
        require(
            set(deps) <= set(ORDER[:index])
            and (index == 0 or ORDER[index - 1] in deps),
            "Canonical queue lacks its serial predecessor",
        )
    return value


def accept_ack(acks, result, config_desc, done):
    index = len(acks)
    require(index < len(LABELS), "More than seventeen primary barriers")
    expected = {
        "execution_episode": EPISODE,
        "sequence": index + 1,
        "label": LABELS[index],
        "pipeline_config": config_desc,
        "completed_jobs": list(done),
        "previous_ack": acks[-1]["ack"] if acks else None,
    }
    require(
        done == ORDER[: min(index + 1, len(ORDER))], "Barrier completed prefix differs"
    )
    require(result.get("binding") == expected, "Archive return binding differs")
    ack = read(checked(result["ack"]))
    require(
        ack.get("schema") == "hepta.github-actions-archive-ack.v1"
        and ack.get("binding") == expected
        and ack.get("readback", {}).get("all_sha256_and_bytes_match") is True,
        "Archive lacks independently verified byte readback",
    )
    require(
        ack.get("manifest") == result["manifest"]
        and ack.get("logical_files") == result["logical_files"]
        and ack.get("items_verified")
        == result["items_verified"]
        == len(result["logical_files"])
        and ack.get("artifact") == result["artifact"]
        and ack.get("cost") == result["cost"],
        "Archive return differs from its immutable ACK",
    )
    checked(result["manifest"])
    require(
        type(ack["artifact"].get("id")) is int and ack["artifact"]["id"] > 0,
        "Real provider immutable artifact ID is absent",
    )
    require(
        all(prior["artifact"]["id"] != ack["artifact"]["id"] for prior in acks),
        "A prior artifact ID was reused",
    )
    if acks:
        previous = read(acks[-1]["ack"])
        require(
            ack["identity"] == previous["identity"],
            "Primary stages must share one actual Actions producer",
        )
    acks.append(copy.deepcopy(result))


def activate(canonical_queue, count, done, acks, previous=None, finalize=False):
    completed = 14 if finalize else count - 1
    require(
        1 <= count <= len(canonical_queue["jobs"]) and (not finalize or count == 14),
        "Invalid active prefix",
    )
    require(
        done == ORDER[:completed] and len(acks) == completed,
        "Activation requires the exact completed and acknowledged prefix",
    )
    if completed:
        ack = acks[-1]
        checked(ack["ack"])
        require(
            ack["binding"]["execution_episode"] == EPISODE
            and ack["binding"]["sequence"] == completed
            and ack["binding"]["label"] == ORDER[completed - 1]
            and ack["binding"]["completed_jobs"] == done,
            "Predecessor ACK differs",
        )
    value = {
        **canonical_queue,
        "jobs": copy.deepcopy(canonical_queue["jobs"][:count]),
        "finalize": finalize,
    }
    if previous:
        size = len(previous["jobs"])
        require(
            value["jobs"][:size] == previous["jobs"] and count in (size, size + 1),
            "Active definition changed or more than one job was released",
        )
    return value
