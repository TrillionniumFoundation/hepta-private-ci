"""Read actual custody/worker bytes; unsigned observations do not confer authority."""

from qualification.hcsn_training.joint_protocol import (
    COST_SCOPE, JSON_CAP, PACKET_CAP, PROFILE, TERMINAL_FIELDS, decode, descriptor,
    encoded, fields, file_digest, input_ref, process, require, root_identity, sha, uint, validate_claim,
    validate_identity,
)

OUTPUT_NAMES = ("candidate.heptapk", "completed.json", "observation.json", "started.json")


def read_inputs(root, reference, sources):
    reference = input_ref(reference)
    directory = root.child("inputs").child(reference["input_id"])
    require(directory.names() == ["manifest.json", "predecessor.heptapk", "request.json"], "input custody closed set")
    manifest = reference["manifest"]
    require(directory.read("manifest.json", JSON_CAP) == encoded(manifest), "manifest original bytes")
    request_raw = directory.read("request.json", JSON_CAP)
    predecessor = directory.read("predecessor.heptapk", PACKET_CAP)
    require(file_digest(request_raw) == dict(sha256=manifest["request_sha256"], bytes=manifest["request_bytes"])
            and file_digest(predecessor) == dict(sha256=manifest["predecessor_sha256"], bytes=manifest["predecessor_bytes"]),
            "input custody byte binding")
    request = sources.contract.validate_request(request_raw)
    require(sources.contract.request_binding_digest(request) == manifest["request_binding_digest"]
            and request["execution_source_digest"] == manifest["worker_execution_source_digest"] == sources.h_digest()
            and request["predecessor_sha256"] == manifest["predecessor_sha256"]
            and request["predecessor_bytes"] == manifest["predecessor_bytes"], "original H request binding")
    directory.check()
    return directory, request, request_raw, predecessor


def validate_outputs(root, job, reservation, sources):
    _, request, request_raw, predecessor = read_inputs(root, reservation["input"], sources)
    directory = job.child(reservation["identity"]["output_id"])
    require(directory.names() == list(OUTPUT_NAMES) and not directory.exists("failed.json"), "success requires exact four outputs")
    raw = {name: directory.read(name, PACKET_CAP if name == "candidate.heptapk" else JSON_CAP)
           for name in OUTPUT_NAMES}
    request_sha = sha(request_raw)
    require(decode(raw["started.json"], JSON_CAP) == dict(schema="hepta.joint-text-worker.started.v1",
            profile=PROFILE, status="started", request_sha256=request_sha), "original start marker")
    require(decode(raw["completed.json"], JSON_CAP) == dict(schema="hepta.joint-text-worker.completed.v1",
            profile=PROFILE, status="complete", request_sha256=request_sha,
            observation_sha256=sha(raw["observation.json"]), candidate_sha256=sha(raw["candidate.heptapk"])),
            "original completion marker")
    observed = sources.contract.validate_observation(raw["observation.json"], request)
    require(observed["request_sha256"] == request_sha
            and observed["execution_sources"] == sources.h_rows()
            and observed["absent_source_paths"] == sources.h_absent()
            and observed["input_files_unchanged"] is True and observed["source_files_unchanged"] is True,
            "original observation/source closure")
    candidate = raw["candidate.heptapk"]
    require(0 < len(candidate) <= min(PACKET_CAP, request["maximum_artifact_bytes"])
            and observed["candidate"]["sha256"] == sha(candidate)
            and observed["candidate"]["bytes"] == len(candidate) and candidate != predecessor,
            "actual candidate byte binding")
    sources.check()
    require(directory.names() == list(OUTPUT_NAMES), "outputs changed during validation")
    for name, original in raw.items():
        require(directory.read(name, len(original)) == original, "output changed during validation")
    return dict(input=reservation["input"], started=file_digest(raw["started.json"]),
                candidate=file_digest(candidate), observation=file_digest(raw["observation.json"]),
                completed=file_digest(raw["completed.json"]))


def read_reservation(root, job, target, sources):
    validate_identity(target)
    raw_descriptor = job.read("descriptor.json", JSON_CAP)
    reference = descriptor(raw_descriptor)
    require(sha(raw_descriptor) == target["payload_sha256"], "retained descriptor hash")
    raw = job.read("reservation.json")
    value = decode(raw)
    fields(value, ("schema_version", "profile", "identity", "input", "root", "nonce",
                   "sources", "absent_sources", "python"))
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["profile"] == PROFILE and value["identity"] == target
            and value["root"] == root.expected and value["input"] == reference, "retained reservation binding")
    root_identity(value["root"])
    input_ref(value["input"])
    require(encoded(value) == raw and tuple(value) == ("schema_version", "profile", "identity", "input", "root",
            "nonce", "sources", "absent_sources", "python"), "canonical reservation bytes")
    from qualification.hcsn_training.joint_protocol import digest
    digest(value["nonce"])
    sources.validate_reservation(value)
    return value


def read_claim(root, job, reservation, sources):
    _, request, _, _ = read_inputs(root, reservation["input"], sources)
    raw = job.read("claim.json", JSON_CAP)
    value = validate_claim(decode(raw, JSON_CAP), reservation["identity"], root.expected, request)
    from qualification.hcsn_training.joint_protocol import CLAIM_FIELDS
    require(encoded(value) == raw and tuple(value) == CLAIM_FIELDS, "canonical claim bytes")
    return value, sha(raw)


def read_worker(job):
    raw = job.read("worker.json", JSON_CAP)
    value = process(decode(raw, JSON_CAP))
    require(encoded(value) == raw and tuple(value) == ("host_id", "process_id", "incarnation"),
            "canonical worker bytes")
    return value


def read_terminal(root, job, reservation, child, sources):
    raw = job.read("terminal.json")
    value = decode(raw)
    fields(value, TERMINAL_FIELDS)
    require(encoded(value) == raw and tuple(value) == TERMINAL_FIELDS, "canonical terminal bytes")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["profile"] == PROFILE and value["identity"] == reservation["identity"]
            and value["input"] == reservation["input"] and value["root"] == root.expected
            and value["process"] == child and value["termination_confirmed"] is True,
            "terminal identity")
    root_identity(value["root"])
    input_ref(value["input"])
    if child is not None:
        process(child)
    require(type(value["reason"]) is str and 0 < len(value["reason"].encode()) <= 256, "terminal reason")
    require(value["returncode"] is None or type(value["returncode"]) is int
            and -255 <= value["returncode"] <= 255, "original OS returncode")
    uint(value["wall_nanoseconds"])
    if value["child_cpu_nanoseconds"] is not None:
        uint(value["child_cpu_nanoseconds"])
    require(value["cost_scope"] == COST_SCOPE and value["physical_energy_joules"] is None
            and value["full_history_cost"] is None, "bounded cost claim")
    claim = None
    if value["claim_sha256"] is not None:
        claim, claim_sha = read_claim(root, job, reservation, sources)
        require(value["claim_sha256"] == claim_sha, "terminal original claim")
    else:
        require(not job.exists("claim.json"), "terminal omits actual claim")
    state = value["state"]
    if state == "succeeded":
        require(type(value["returncode"]) is int and value["returncode"] == 0 and child is not None
                and value["claim_sha256"] is not None
                and value["reason"] == "worker_exit_zero_and_outputs_closed", "normal child success required")
        require(claim is not None and value["wall_nanoseconds"] <= claim["budget_milliseconds"] * 1000000,
                "retained success exceeded original absolute budget")
        outputs = validate_outputs(root, job, reservation, sources)
        require(value["outputs"] == outputs, "terminal output evidence changed")
        evidence = dict(kind="completed", terminal=file_digest(raw), outputs=outputs)
    else:
        require(state in ("failed", "cancelled") and value["outputs"] is None, "stopped outcome")
        evidence = dict(kind="stopped", terminal=file_digest(raw))
    require(job.read("terminal.json") == raw, "terminal changed during observation")
    return state, evidence
