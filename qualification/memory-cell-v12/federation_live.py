"""Concurrent three-VM qualification via GitHub artifact relay.

One controller owns SQLite; three long-lived worker processes compute candidates.
Only that controller releases them. Trust is the exact GitHub workflow/run and
cooperative jobs, not signatures, peer consensus or hardware attestation. No
artifact runtime credentials are read: downloads use the ordinary GITHUB_TOKEN,
uploads are delegated to the pinned upload-artifact action in the workflow.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from federation import Authority, Denied, canonical, digest, file_digest, infer, read_json, seal_bundle, verify_bundle, write_json
from federation_experiment import candidate, distinct, identity, rejected, source_stage, task_binding


NODES = ("replica-a", "replica-b")
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXTRACTED = 64 * 1024 * 1024
MAX_RPC = 4 * 1024 * 1024
LIMITS = dict(trusted_github_jobs=True, trusted_single_controller=True,
              live_artifact_relay=True, distributed_consensus=False,
              native_rust_owner_authority_integration=False, hardware_attestation=False,
              physical_host_failure=False, partition_availability=False,
              mathematical_unlearning=False, optimizer_migration=False,
              production_activation_allowed=False, artifact_retention_days=30)


def name(label):
    return "memory-v12-live-" + label + "-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(path):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise Denied("standard GitHub token unavailable for actions:read")
    request = urllib.request.Request("https://api.github.com/" + path, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "hepta-memory-v12-live"})
    return urllib.request.build_opener(NoRedirect).open(request, timeout=20)


def extract_archive(raw, destination):
    if len(raw) > MAX_ARCHIVE:
        raise Denied("artifact compressed-size budget exceeded")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 512 or sum(m.file_size for m in members) > MAX_EXTRACTED:
            raise Denied("artifact expansion budget exceeded")
        paths = set()
        for member in members:
            relative = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (relative.is_absolute() or ".." in relative.parts or "\\" in member.filename or
                    ":" in member.filename or stat.S_ISLNK(mode) or str(relative) in paths):
                raise Denied("unsafe or duplicate artifact member")
            paths.add(str(relative))
        destination.mkdir(parents=True, exist_ok=False)
        for member in members:
            path = destination.joinpath(*PurePosixPath(member.filename).parts)
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as target:
                    target.write(archive.read(member))


def wait_artifact(label, destination, timeout=600):
    """Same-run REST reads; redirect credentials never cross the API origin."""
    repository, run = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"]
    wanted, start = name(label), time.monotonic()
    while time.monotonic() - start < timeout:
        with api(f"repos/{repository}/actions/runs/{run}/artifacts?per_page=100") as response:
            listing = json.load(response)
        if listing["total_count"] > 100:
            raise Denied("unexpectedly large run artifact inventory")
        matches = [a for a in listing["artifacts"] if a["name"] == wanted and not a["expired"]]
        if len(matches) > 1:
            raise Denied("ambiguous transport artifact")
        if matches:
            artifact = matches[0]
            if artifact["workflow_run"]["head_sha"] != os.environ["GITHUB_SHA"] or artifact["size_in_bytes"] > MAX_ARCHIVE:
                raise Denied("artifact source SHA or size mismatch")
            try:
                with api(f"repos/{repository}/actions/artifacts/{artifact['id']}/zip") as response:
                    raw = response.read(MAX_ARCHIVE + 1)
            except urllib.error.HTTPError as error:
                if error.code not in (301, 302, 303, 307, 308):
                    raise Denied("GitHub archive request failed with HTTP " + str(error.code)) from None
                location = error.headers.get("Location", "")
                parsed = urllib.parse.urlsplit(location)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise Denied("unsafe GitHub archive redirect")
                # Intentionally make a new, credential-free request. Never log
                # the short-lived signed redirect URL or Authorization value.
                with urllib.request.urlopen(location, timeout=30) as response:
                    raw = response.read(MAX_ARCHIVE + 1)
            checksum = hashlib.sha256(raw).hexdigest()
            advertised = artifact.get("digest")
            if advertised and advertised != "sha256:" + checksum:
                raise Denied("GitHub artifact archive digest mismatch")
            extract_archive(raw, destination)
            transport = dict(artifact_id=artifact["id"], name=wanted, archive_sha256=checksum,
                             advertised_digest_verified=bool(advertised), archive_bytes=len(raw),
                             wait_and_download_wall_seconds=time.monotonic() - start)
            write_json(destination / "TRANSPORT.json", transport)
            return transport
        time.sleep(3)
    raise Denied("timed out waiting for same-run artifact " + wanted)


def message(path, label, binding, body):
    path.mkdir(parents=True, exist_ok=True)
    value = dict(schema="hepta.memory.live.v1", label=label, binding=binding, body=body,
                 limits=LIMITS, executed_source={p: file_digest(Path(__file__).with_name(p))
                     for p in ("federation_live.py", "federation.py", "federation_experiment.py")})
    write_json(path / "message.json", value)
    return value


def receive(state, label, binding):
    path = state / "received" / label
    transport = wait_artifact(label, path)
    value = read_json(path / "message.json")
    if value["schema"] != "hepta.memory.live.v1" or value["label"] != label or value["binding"] != binding:
        raise Denied("message scope mismatch")
    return value["body"], transport, file_digest(path / "message.json")


def serve(state):
    context = read_json(state / "context.json")
    worker = identity(context["node"])
    initial = infer(context["bundle"], context["binding"], context["checkpoint"])
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(state / "service.sock"))
    (state / "service.sock").chmod(0o600)
    listener.listen(4)
    listener.settimeout(2)
    write_json(state / "ready.json", dict(identity=worker, checkpoint=context["checkpoint"],
               initial_output_sha256=digest(initial), started_at_ns=time.time_ns()))
    sequence, deadline = 0, time.monotonic() + 1800
    while time.monotonic() < deadline:
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            continue
        with connection:
            connection.settimeout(30)
            request = json.loads(connection.makefile("rb").readline(MAX_RPC + 1))
            sequence += 1
            reply = dict(request_id=request["request_id"], server=worker, sequence=sequence,
                         operation=request["operation"], serving_authorized=False)
            if request["operation"] == "compute":
                ticket = request["ticket"]
                if (ticket["binding"] != context["binding"] or ticket["checkpoint"] != context["checkpoint"] or
                        ticket["node"] != context["node"]):
                    raise Denied("worker request belongs to a different cell/run/node")
                output = infer(context["bundle"], context["binding"], context["checkpoint"])
                reply["candidate"] = candidate(context["node"], ticket, output)
            elif request["operation"] == "acquire":
                reply["read_request"] = dict(binding=context["binding"], node=context["node"],
                    checkpoint=context["checkpoint"], request_id=request["request_id"], permission="read",
                    seen_epoch=request["seen_epoch"], revocation_sha256=request["revocation_sha256"])
            elif request["operation"] not in ("status", "stop"):
                raise Denied("unsupported worker operation")
            with (state / "service.jsonl").open("ab") as log:
                log.write(canonical(reply) + b"\n")
                log.flush()
            connection.sendall(canonical(reply) + b"\n")
        if request["operation"] == "stop":
            listener.close()
            write_json(state / "stopped.json", dict(identity=worker, sequence=sequence))
            return
    raise Denied("worker lifetime budget exhausted")


def rpc(state, operation, **kwargs):
    ready = read_json(state / "ready.json")
    request = dict(request_id=secrets.token_hex(16), operation=operation, **kwargs)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(30)
        client.connect(str(state / "service.sock"))
        client.sendall(canonical(request) + b"\n")
        raw = client.makefile("rb").readline(MAX_RPC + 1)
    if len(raw) > MAX_RPC:
        raise Denied("worker response size exceeded")
    reply = json.loads(raw)
    previous = read_json(state / "last-sequence.json")["sequence"] if (state / "last-sequence.json").exists() else 0
    if (reply["request_id"] != request["request_id"] or reply["server"] != ready["identity"] or
            reply["sequence"] <= previous or reply["serving_authorized"] is not False):
        raise Denied("worker changed process/boot, replayed a reply, or claimed serving authority")
    write_json(state / "last-sequence.json", dict(sequence=reply["sequence"]))
    return reply


def start_worker(state, node, bundle, binding, checkpoint):
    state.mkdir(parents=True, exist_ok=False)
    write_json(state / "context.json", dict(node=node, bundle=str(bundle.resolve()), binding=binding, checkpoint=checkpoint))
    log = (state / "worker.log").open("wb")
    environment = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
    subprocess.Popen([sys.executable, __file__, "serve", "--state", str(state)],
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=environment)
    log.close()
    deadline = time.monotonic() + 20
    while not (state / "ready.json").exists():
        if time.monotonic() > deadline:
            raise Denied("worker did not become ready")
        time.sleep(.05)
    return rpc(state, "status")


def same_worker(earlier, later):
    if earlier["server"] != later["server"] or later["sequence"] <= earlier["sequence"]:
        raise Denied("a prepared worker did not remain the same live process")


def expected_state(control, context, epoch, owner, valid=1):
    if control.state() != dict(epoch=epoch, owner=owner, checkpoint=context["checkpoint"], valid=valid):
        raise Denied("controller stage received stale or unexpected authority state")


def bootstrap(args):
    args.state.mkdir(parents=True, exist_ok=False)
    source_stage(args.input, args.out)
    stage = read_json(args.out / "stage.json")
    binding, checkpoint = stage["binding"], stage["checkpoint"]
    shutil.copyfile(args.out / "authority.sqlite", args.state / "authority.sqlite")
    owner = start_worker(args.state / "worker", "source", args.out / "bundle", binding, checkpoint)
    context = dict(binding=binding, checkpoint=checkpoint, bootstrap=stage, owner=owner)
    write_json(args.state / "context.json", context)
    message(args.out, "bootstrap", binding, dict(owner=owner, checkpoint=checkpoint,
            controller_identity=identity("controller"), model_sha256=file_digest(args.out / "bundle/model.json"),
            probes_sha256=file_digest(args.out / "bundle/probes.json")))


def prepare(args):
    args.state.mkdir(parents=True, exist_ok=False)
    downloaded = args.state / "received/bootstrap"
    transport = wait_artifact("bootstrap", downloaded)
    envelope = read_json(downloaded / "message.json")
    binding = task_binding(envelope["binding"]["nonce"])
    if envelope["binding"] != binding or envelope["label"] != "bootstrap":
        raise Denied("bootstrap task mismatch")
    stage, body = read_json(downloaded / "stage.json"), envelope["body"]
    if stage["binding"] != binding or stage["checkpoint"] != body["checkpoint"]:
        raise Denied("bootstrap checkpoint mismatch")
    for filename in ("model.json", "probes.json"):
        expected = body[filename.split(".")[0] + "_sha256"]
        committed = Path(__file__).parent / "evidence/content" / filename
        if file_digest(committed) != expected or file_digest(downloaded / "bundle" / filename) != expected:
            raise Denied("producer substituted the committed model or probes")
    checkpoint = body["checkpoint"]
    verify_bundle(downloaded / "bundle", binding, checkpoint)
    shutil.copytree(downloaded / "bundle", args.state / "bundle")
    for path in (args.state / "bundle").iterdir():
        path.chmod(0o444)
    started = start_worker(args.state / "worker", args.node, args.state / "bundle", binding, checkpoint)
    response = rpc(args.state / "worker", "compute", ticket=stage["tickets"][args.node]["normal"])
    same_worker(started, response)
    context = dict(binding=binding, checkpoint=checkpoint, node=args.node, prepared=response)
    write_json(args.state / "context.json", context)
    prepared = dict(binding=binding, node=args.node, epoch=1, checkpoint=checkpoint,
                    read_grant=response["candidate"]["ticket"]["grant"], verified_checkpoint=True)
    message(args.out, "prepared-" + args.node, binding,
            dict(prepared=prepared, response=response, transport=transport, worker_stays_alive=True))


def migrate(args, context):
    binding, checkpoint = context["binding"], context["checkpoint"]
    prepared = {n: receive(args.state, "prepared-" + n, binding)[0] for n in NODES}
    distinct([context["owner"]["server"], *[p["response"]["server"] for p in prepared.values()]])
    control = Authority(args.state / "authority.sqlite", binding)
    expected_state(control, context, 1, "source")
    before = rpc(args.state / "worker", "compute", ticket=context["bootstrap"]["tickets"]["source"]["pending"])
    same_worker(context["owner"], before)
    releases = {n: control.release(p["response"]["candidate"]) for n, p in prepared.items()}
    checks = []
    rejected(checks, "readonly_cannot_write_before_handoff", lambda: control.authorize_write("replica-b", 1, checkpoint))
    control.migrate("replica-a", expected_epoch=1, expected_owner="source", prepared=prepared["replica-a"]["prepared"])
    expected_state(control, context, 2, "replica-a")
    tickets = {n: {k: control.issue(n) for k in ("normal", "pending")} for n in NODES}
    control.close()
    body = dict(checkpoint=checkpoint, state=dict(epoch=2, owner="replica-a", checkpoint=checkpoint, valid=1),
                tickets=tickets, prepared=prepared, releases=releases, owner_before=before, checks=checks)
    message(args.out, "epoch2", binding, body)
    write_json(args.state / "epoch2.json", body)
    write_json(args.state / "epoch2-sha.json", dict(sha256=file_digest(args.out / "message.json")))


def readback(args, context):
    body, transport, checksum = receive(args.state, "epoch2", context["binding"])
    if body["checkpoint"] != context["checkpoint"] or body["state"]["epoch"] != 2:
        raise Denied("invalid activation message")
    replies = {k: rpc(args.state / "worker", "compute", ticket=t) for k, t in body["tickets"][args.node].items()}
    same_worker(context["prepared"], replies["normal"])
    same_worker(replies["normal"], replies["pending"])
    write_json(args.state / "readback.json", replies)
    message(args.out, "readback-" + args.node, context["binding"],
            dict(replies=replies, activation_sha256=checksum, transport=transport, worker_stays_alive=True))


def revoke(args, context):
    binding, checkpoint = context["binding"], context["checkpoint"]
    activated = read_json(args.state / "epoch2.json")
    activation_sha = read_json(args.state / "epoch2-sha.json")["sha256"]
    readbacks = {n: receive(args.state, "readback-" + n, binding)[0] for n in NODES}
    control = Authority(args.state / "authority.sqlite", binding)
    expected_state(control, context, 2, "replica-a")
    releases = {}
    for node, receipt in readbacks.items():
        if receipt["activation_sha256"] != activation_sha:
            raise Denied("readback did not observe this activation")
        same_worker(activated["prepared"][node]["response"], receipt["replies"]["normal"])
        same_worker(receipt["replies"]["normal"], receipt["replies"]["pending"])
        releases[node] = control.release(receipt["replies"]["normal"]["candidate"])
    checks = list(activated["checks"])
    ticket = context["bootstrap"]["tickets"]["source"]["pending"]
    old_owner = rpc(args.state / "worker", "compute", ticket=ticket)
    same_worker(activated["owner_before"], old_owner)
    rejected(checks, "live_old_owner_read_fenced_after_migration", lambda: control.release(old_owner["candidate"]))
    rejected(checks, "live_old_owner_write_fenced", lambda: control.authorize_write("source", 1, checkpoint))
    rejected(checks, "old_owner_cannot_claim_current_epoch", lambda: control.authorize_write("source", 2, checkpoint))
    rejected(checks, "replica_remains_readonly", lambda: control.authorize_write("replica-b", 2, checkpoint))
    control.authorize_write("replica-a", 2, checkpoint)
    control.revoke(checkpoint)
    old_after_revoke = rpc(args.state / "worker", "compute", ticket=ticket)
    same_worker(old_owner, old_after_revoke)
    rejected(checks, "live_old_owner_read_fenced_after_revocation", lambda: control.release(old_after_revoke["candidate"]))
    for node, receipt in readbacks.items():
        rejected(checks, "pending_revoked:" + node, lambda r=receipt: control.release(r["replies"]["pending"]["candidate"]))
    expected_state(control, context, 3, "replica-a", valid=0)
    control.close()
    body = dict(checkpoint=checkpoint, epoch=3, readbacks=readbacks, fresh_releases=releases,
                old_owner_after_migration=old_owner, old_owner_after_revocation=old_after_revoke, checks=checks)
    message(args.out, "revoked", binding, body)
    write_json(args.state / "revoked.json", body)
    write_json(args.state / "revoked-sha.json", dict(sha256=file_digest(args.out / "message.json")))


def request_after_revocation(args, context):
    body, transport, checksum = receive(args.state, "revoked", context["binding"])
    if body["checkpoint"] != context["checkpoint"] or body["epoch"] != 3:
        raise Denied("invalid revocation message")
    response = rpc(args.state / "worker", "acquire", seen_epoch=3, revocation_sha256=checksum)
    same_worker(read_json(args.state / "readback.json")["pending"], response)
    write_json(args.state / "post-revocation-request.json", response)
    message(args.out, "request-" + args.node, context["binding"],
            dict(response=response, transport=transport, worker_stays_alive=True))


def stop_worker(state):
    if (state / "stopped.json").exists():
        return read_json(state / "stopped.json")
    stopped = rpc(state, "stop")
    deadline = time.monotonic() + 5
    while not (state / "stopped.json").exists():
        if time.monotonic() > deadline:
            raise Denied("worker acknowledged stop but did not close its service")
        time.sleep(.05)
    return stopped


def finish(args, context):
    binding, checkpoint = context["binding"], context["checkpoint"]
    revoked = read_json(args.state / "revoked.json")
    revocation_sha = read_json(args.state / "revoked-sha.json")["sha256"]
    requests = {n: receive(args.state, "request-" + n, binding)[0] for n in NODES}
    control = Authority(args.state / "authority.sqlite", binding)
    expected_state(control, context, 3, "replica-a", valid=0)
    checks, denials = list(revoked["checks"]), {}
    for node, envelope in requests.items():
        response = envelope["response"]
        same_worker(revoked["readbacks"][node]["replies"]["pending"], response)
        request = response["read_request"]
        if request != dict(binding=binding, node=node, checkpoint=checkpoint, request_id=response["request_id"],
                           permission="read", seen_epoch=3, revocation_sha256=revocation_sha):
            raise Denied("fresh request did not observe the authoritative revocation")
        rejected(checks, "fresh_read_denied_after_revocation:" + node, lambda n=node: control.issue(n))
        denials[node] = dict(request_id=request["request_id"], denied=True, epoch=3, reason=checks[-1]["reason"])
    owner_status = rpc(args.state / "worker", "status")
    same_worker(revoked["old_owner_after_revocation"], owner_status)
    identities = [owner_status["server"], *[r["response"]["server"] for r in requests.values()]]
    distinct(identities)
    controller_identity = identity("controller")
    if controller_identity["instance_sha256"] != owner_status["server"]["instance_sha256"]:
        raise Denied("controller moved away from its original owner VM")
    state = control.state()
    write_json(args.out / "events.json", [dict(x) for x in control.db.execute("SELECT * FROM events ORDER BY seq")])
    control.close()
    shutil.copyfile(args.state / "authority.sqlite", args.out / "authority.sqlite")
    owner_stop = stop_worker(args.state / "worker")
    shutil.copyfile(args.state / "worker/service.jsonl", args.out / "source-service.jsonl")
    message(args.out, "final", binding, dict(passed=True, checkpoint=checkpoint, state=state,
            controller_identity=controller_identity, stable_workers=identities, independent_runner_instances=3,
            denials=denials, requests=requests, checks=checks, owner_still_alive_at_final=owner_status,
            owner_stop=owner_stop, revocation=revoked, same_pid_prepare_activate_readback_revoke=True,
            authority_sha256=file_digest(args.out / "authority.sqlite")))


def acknowledge(args, context):
    final, transport, checksum = receive(args.state, "final", context["binding"])
    request = read_json(args.state / "post-revocation-request.json")
    denial = final["denials"][args.node]
    if not final["passed"] or not denial["denied"] or denial["request_id"] != request["request_id"] or denial["epoch"] != 3:
        raise Denied("no matching denial for this live worker's fresh request")
    still_alive = rpc(args.state / "worker", "status")
    same_worker(request, still_alive)
    stopped = stop_worker(args.state / "worker")
    shutil.copyfile(args.state / "worker/service.jsonl", args.out / "service.jsonl")
    message(args.out, "completed-" + args.node, context["binding"],
            dict(passed=True, final_sha256=checksum, transport=transport, still_alive=still_alive, stopped=stopped))


def selftest(source):
    """Actual local processes only; never emit a cross-VM success receipt."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        binding = dict(schema="local-functional-test-only", nonce=secrets.token_hex(16))
        checkpoint = seal_bundle(source, root / "bundle", binding)
        probes = read_json(root / "bundle/probes.json")
        control = Authority(root / "authority.sqlite", binding, initial=dict(checkpoint=checkpoint, probes=probes))
        workers = {}
        try:
            for node in ("source", *NODES):
                workers[node] = start_worker(root / node, node, root / "bundle", binding, checkpoint)
            tickets = {n: control.issue(n) for n in workers}
            replies = {n: rpc(root / n, "compute", ticket=t) for n, t in tickets.items()}
            for node in NODES:
                control.release(replies[node]["candidate"])
            prepared = dict(binding=binding, node="replica-a", epoch=1, checkpoint=checkpoint,
                            read_grant=tickets["replica-a"]["grant"], verified_checkpoint=True)
            control.migrate("replica-a", expected_epoch=1, expected_owner="source", prepared=prepared)
            old = rpc(root / "source", "compute", ticket=tickets["source"])
            same_worker(replies["source"], old)
            checks = []
            rejected(checks, "live_old_owner_rejected", lambda: control.release(old["candidate"]))
            for node in NODES:
                newer = rpc(root / node, "compute", ticket=control.issue(node))
                same_worker(replies[node], newer)
                control.release(newer["candidate"])
            control.revoke(checkpoint)
            for node in NODES:
                rpc(root / node, "acquire", seen_epoch=3, revocation_sha256="local-test")
                rejected(checks, node + ":new_request_denied", lambda n=node: control.issue(n))
            bad_zip = io.BytesIO()
            with zipfile.ZipFile(bad_zip, "w") as archive:
                archive.writestr("../escape", "denied")
            rejected(checks, "zip_traversal_denied", lambda: extract_archive(bad_zip.getvalue(), root / "bad"))
            print(json.dumps(dict(local_functional_only=True, checks=checks, worker_pids=[w["server"]["pid"] for w in workers.values()])))
        finally:
            control.close()
            for node in workers:
                stop_worker(root / node)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("bootstrap", "prepare", "migrate", "readback", "revoke", "request", "finish", "ack", "serve", "cleanup", "selftest"))
    parser.add_argument("--state", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--input", type=Path, default=Path(__file__).parent / "evidence/content")
    parser.add_argument("--node", choices=("source", *NODES), default="source")
    args = parser.parse_args()
    if args.phase == "serve":
        serve(args.state)
        return
    if args.phase == "selftest":
        selftest(args.input)
        return
    if args.phase == "cleanup":
        if (args.state / "worker/ready.json").exists():
            stop_worker(args.state / "worker")
        return
    args.state, args.out = args.state.resolve(), args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        if args.phase == "bootstrap":
            bootstrap(args)
        elif args.phase == "prepare":
            prepare(args)
        else:
            context = read_json(args.state / "context.json")
            if context["binding"] != task_binding(context["binding"]["nonce"]):
                raise Denied("live context belongs to another task")
            operations = dict(migrate=migrate, readback=readback, revoke=revoke,
                              request=request_after_revocation, finish=finish, ack=acknowledge)
            operations[args.phase](args, context)
        write_json(args.out / "timing.json", dict(wall_seconds=time.monotonic() - started))
    except Exception as error:
        write_json(args.out / "blocked.json", dict(phase=args.phase, error_type=type(error).__name__,
                    error=str(error), passed=False, wall_seconds=time.monotonic() - started))
        raise


if __name__ == "__main__":
    main()
