"""Engineering intake and publication; production original-turn consent is unavailable."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile

from . import data, paired_cold, paired_freeze

ORIGINAL_TURN_VERIFIER_REQUIRED = (
    "ORIGINAL_TURN_VERIFIER_REQUIRED: owner intake requires the protected "
    "original-turn consent verifier; historical native v1 receipts remain unqualified"
)


def require(value, message):
    if not value:
        raise ValueError(message)


def require_engineering_scope(scope):
    # Historical ELF pins cannot acquire the missing original-runtime boundary
    # from a new Python wrapper. This has no operator override or legacy fallback.
    require(scope == "engineering_fixture", ORIGINAL_TURN_VERIFIER_REQUIRED)


def digest_field(value):
    require(
        isinstance(value, str)
        and re.fullmatch("[0-9a-f]{64}", value)
        and value != "0" * 64,
        "expected nonzero SHA-256",
    )
    return value


def sha(value):
    return hashlib.sha256(value).hexdigest()


def open_database(home):
    mode = home.lstat()
    require(
        stat.S_ISDIR(mode.st_mode)
        and mode.st_uid == os.geteuid()
        and mode.st_mode & 0o077 == 0,
        "intake home must be private and owner-controlled",
    )
    database = home / "intake.sqlite"
    entry = database.lstat()
    require(
        stat.S_ISREG(entry.st_mode)
        and entry.st_uid == mode.st_uid
        and entry.st_mode & 0o077 == 0,
        "original intake database must be a private regular file",
    )
    db = sqlite3.connect(
        database.absolute().as_uri() + "?mode=rw",
        uri=True,
        isolation_level=None,
        timeout=30,
    )
    db.execute("PRAGMA synchronous=FULL")
    return db


def inbox_identity(fd):
    info = os.fstat(fd)
    require(
        stat.S_ISDIR(info.st_mode) and info.st_mode & 0o022 == 0,
        "source witness directory permits other writers",
    )
    return [info.st_dev, info.st_ino, info.st_uid]


@contextlib.contextmanager
def owner_file(config, basename):
    folder = os.open(config["inbox"], os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY)
    try:
        require(
            inbox_identity(folder) == config["inbox_identity"],
            "source witness owner or directory changed",
        )
        file = os.open(
            basename, os.O_NOFOLLOW | os.O_RDONLY | os.O_NONBLOCK, dir_fd=folder
        )
        with os.fdopen(file, "rb") as f:
            m = os.fstat(f.fileno())
            require(
                stat.S_ISREG(m.st_mode)
                and m.st_uid == config["inbox_identity"][2]
                and m.st_mode & 0o022 == 0,
                "source witness is not owner-controlled",
            )
            yield f
    finally:
        os.close(folder)


def witness(config, name):
    with owner_file(config, name + ".json") as f:
        raw = f.read(32769)
    require(len(raw) <= 32768, "oversized source witness")
    item = json.loads(raw)
    require(
        item["study_sha256"] == config["study"]
        and item["freeze_sha256"] == config["freeze"],
        "source witness study/freeze differs",
    )
    require(
        type(item["sequence"]) is int and 0 < item["sequence"] < 2**63,
        "invalid source sequence",
    )
    return item


def install(args):
    require(
        args.scope in ("owner_intake", "engineering_fixture"), "invalid intake scope"
    )
    require_engineering_scope(args.scope)
    snapshot = json.loads(args.snapshot.read_bytes())
    require(
        data.digest(snapshot) == digest_field(args.freeze),
        "wrong frozen snapshot",
    )
    path = args.inbox.resolve(strict=True)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        identity = inbox_identity(fd)
    finally:
        os.close(fd)
    config = dict(
        study=digest_field(args.study),
        freeze=args.freeze,
        scope=args.scope,
        inbox=str(path),
        inbox_identity=identity,
        native=str(args.native.resolve(strict=True)),
        native_sha256=digest_field(args.native_sha256),
    )
    with open(config["native"], "rb") as f:
        if args.scope == "owner_intake":
            require(
                f.read(4) == b"\x7fELF",
                "owner intake requires its registered native Linux binary",
            )
            f.seek(0)
        require(
            hashlib.file_digest(f, "sha256").hexdigest() == config["native_sha256"],
            "unexpected native executable",
        )
    anchor = witness(config, "freeze")
    require(
        anchor["schema"] == "hepta.paired-intake.freeze-observation.v1",
        "wrong original freeze observation",
    )
    if (
        args.scope == "owner_intake"
        and "paired_source_exposure" in snapshot["candidate"]
    ):
        from . import paired_source_dispatch

        receipt = (
            getattr(args, "source_retention", None)
            or args.snapshot.parent / "RETENTION.json"
        )
        config["qualified_source_retention"] = paired_source_dispatch.authorize(
            snapshot, anchor, receipt
        )
    config["anchor"] = anchor
    import fcntl

    with tempfile.TemporaryDirectory(dir=args.home.parent) as tmp:
        staged = Path(tmp) / "store"
        staged.mkdir(mode=0o700)
        path = staged / "intake.sqlite"
        with path.open("xb") as f:
            os.fchmod(f.fileno(), 0o600)
        with contextlib.closing(open_database(staged)) as db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE settings(value TEXT NOT NULL);
                CREATE TABLE admissions(id TEXT PRIMARY KEY, arrival TEXT NOT NULL UNIQUE,
                    sequence INTEGER NOT NULL UNIQUE, request_sha TEXT NOT NULL UNIQUE,
                    request_json BLOB NOT NULL, binding BLOB NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('ready','publishing','released')));
                CREATE TABLE used(kind TEXT NOT NULL, digest TEXT NOT NULL, admission TEXT NOT NULL,
                    PRIMARY KEY(kind,digest));
            """)
            db.execute("INSERT INTO settings VALUES (?)", (json.dumps(config),))
            db.commit()
        sync_dir(staged)
        # Installers sharing a study home publish a complete database exactly once.
        parent_fd = os.open(args.home.parent, os.O_DIRECTORY | os.O_RDONLY)
        try:
            fcntl.flock(parent_fd, fcntl.LOCK_EX)
            require(not os.path.lexists(args.home), "study home already exists")
            os.rename(staged, args.home)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)


def verify_live(
    native_path,
    native_sha256,
    study_sha256,
    delivery_id,
    scope,
    launch,
    *,
    expected_principal=None,
    evidence_scope="owner_intake",
):
    """Exercise a pinned fixture; production v1 owner verification is unavailable."""
    require_engineering_scope(evidence_scope)
    for fd in (3, 4):
        os.fstat(fd)
    study = digest_field(study_sha256)
    delivery = digest_field(delivery_id)
    if scope.get("use") == "train" and set(scope) == {"use", "failure", "correction"}:
        failure, correction = (
            digest_field(scope[k]) for k in ("failure", "correction")
        )
        use_text = (
            "I authorize Hepta to train the study candidate using only these records.\n"
            f"Failure SHA-256: {failure}\nCorrection SHA-256: {correction}"
        )
    elif scope.get("use") == "evaluate_only" and set(scope) == {
        "use",
        "freeze",
        "task",
    }:
        freeze, task = (digest_field(scope[k]) for k in ("freeze", "task"))
        use_text = (
            "I authorize Hepta to evaluate the frozen pair on this task. Training on this task is prohibited.\n"
            f"Pair freeze SHA-256: {freeze}\nTask SHA-256: {task}"
        )
    else:
        raise ValueError("invalid paired learning use")
    req = dict(study_sha256=study, delivery_id=delivery, scope=scope)
    with open(native_path, "rb") as f:
        require(
            hashlib.file_digest(f, "sha256").hexdigest() == digest_field(native_sha256),
            "native executable changed",
        )
        fd = f.fileno()
        with subprocess.Popen(
            [f"/proc/self/fd/{fd}", *launch],
            env={"PATH": os.defpath, "LANG": "C"},
            pass_fds=(3, 4, fd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ) as proc:
            try:
                out, _ = proc.communicate(data.canonical(req), timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
            require(
                proc.returncode == 0 and len(out) <= 32768,
                "original native consent was not verified",
            )
    answer = json.loads(out)
    principal = digest_field(answer["study_principal_sha256"])
    text = f"Hepta paired learning consent v1\nStudy SHA-256: {study}\n{use_text}"
    expected = dict(
        schema="hepta.paired-learning.consent-readback.v1",
        study_sha256=study,
        delivery_id=delivery,
        use=scope["use"],
        consent_text_sha256=sha(text.encode()),
        study_principal_sha256=principal,
    )
    require(
        answer == expected
        and (expected_principal is None or principal == expected_principal),
        "native scope, principal or signed statement differs from original event",
    )
    return answer


def intake_keys(record, arrival, token):
    source = record["source"]
    yield "authorization", arrival["consent_delivery_id"]
    yield "original-arrival", arrival["arrival_id"]
    yield "original-record", data.record_digest(record)
    yield "input-tokens", token
    yield "record-id", data.digest(record["record_id"])
    if source.get("intake_receipt_sha256"):
        yield "original-receipt", digest_field(source["intake_receipt_sha256"])
    else:
        yield (
            "source-item",
            data.digest([source["sha256"], source.get("row_zero_based")]),
        )
    for field in ("original_task_id", "operation_id"):
        if field in source:
            yield field, data.digest([source["repository"], source[field]])


def admit(args):
    # These are launch-time capabilities. No file or database may take a missing slot first.
    for fd in (3, 4):
        os.fstat(fd)
    with contextlib.closing(open_database(args.home)) as db:
        config = json.loads(db.execute("SELECT value FROM settings").fetchone()[0])
        require_engineering_scope(config["scope"])
        require(
            witness(config, "freeze") == config["anchor"],
            "original freeze observation changed",
        )
        qualified_retention = None
        if config["scope"] == "owner_intake":
            snapshot = json.loads(args.snapshot.read_bytes())
            require(
                data.digest(snapshot) == config["freeze"],
                "different frozen pair at intake",
            )
            if "paired_source_exposure" in snapshot["candidate"]:
                qualified_retention = config.get("qualified_source_retention")
                if not qualified_retention or qualified_retention != config[
                    "anchor"
                ].get("source_retention_sha256"):
                    from . import paired_source_dispatch

                    receipt = (
                        getattr(args, "source_retention", None)
                        or args.snapshot.parent / "RETENTION.json"
                    )
                    qualified_retention = paired_source_dispatch.authorize(
                        snapshot, config["anchor"], receipt
                    )
        arrival = witness(config, digest_field(args.arrival))
        fields = (
            "arrival_id",
            "record_sha256",
            "consent_delivery_id",
            "study_principal_sha256",
        )
        for key in fields:
            digest_field(arrival[key])
        require(
            arrival["schema"] == "hepta.paired-intake.first-observation.v1"
            and arrival["arrival_id"] == args.arrival
            and arrival["sequence"] > config["anchor"]["sequence"],
            "arrival is not witnessed after freeze",
        )
        native = verify_live(
            config["native"],
            config["native_sha256"],
            config["study"],
            arrival["consent_delivery_id"],
            dict(
                use="evaluate_only",
                freeze=config["freeze"],
                task=arrival["record_sha256"],
            ),
            [args.root_pid, str(args.sqlite_home), str(args.route)],
            expected_principal=arrival["study_principal_sha256"],
            evidence_scope=config["scope"],
        )
        # The record is first read after live consent verification. Stage those exact bytes.
        with args.future.open("rb") as stream:
            raw = stream.read(data.MAX_RECORD_BYTES + 65)
        require(
            len(raw) <= data.MAX_RECORD_BYTES + 64,
            "incoming record exceeds the study limit",
        )
        rows = json.loads(raw)
        require(
            isinstance(rows, list)
            and len(rows) == 1
            and data.record_digest(rows[0]) == arrival["record_sha256"],
            "single original authorized record required",
        )
        record = rows[0]
        require(
            record["origin_kind"] == "authorized_agent_run"
            and record["exposure"] == "unexposed"
            and record["authorization"]["evaluation_allowed"] is True,
            "record is not authorized for future evaluation",
        )
        with tempfile.TemporaryDirectory(dir=args.home) as temp:
            folder = Path(temp)
            future, path = folder / "future.json", folder / "paired.json"
            future.write_bytes(data.canonical(rows))
            request_sha = paired_freeze.assemble(
                args.snapshot, config["freeze"], future, path, materials=args.materials
            )
            request = paired_cold.checked_request(path, request_sha)
            for arm in ("parent", "candidate"):
                require(
                    paired_cold.verify_materials(request[arm], args.materials)
                    == data.digest(request[arm]),
                    "frozen material differs",
                )
            tokens = [
                paired_cold.token_inputs(request, request[arm], args.materials)[
                    record["task_id"]
                ]
                for arm in ("parent", "candidate")
            ]
            require(tokens[0] == tokens[1], "parent and child input token IDs differ")
        release = dict(
            schema="hepta.paired-intake.release.v1",
            study_sha256=config["study"],
            freeze_sha256=config["freeze"],
            candidate_sha256=data.digest(request["candidate"]),
            request_sha256=request_sha,
            scope=config["scope"],
        )
        if qualified_retention is not None:
            release["source_retention_sha256"] = digest_field(qualified_retention)
        binding = dict(
            anchor=config["anchor"],
            arrival=arrival,
            native=native,
            native_sha256=config["native_sha256"],
            release=release,
        )
        if args.training_run is not None:
            from . import paired_people

            binding["enrollment"] = paired_people.check(
                config,
                arrival,
                native,
                request_sha,
                release["candidate_sha256"],
                args.training_run,
            )
        admission = data.digest(binding)
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT id FROM admissions WHERE arrival=?", (args.arrival,)
        ).fetchone()
        if prior:
            require(
                prior == (admission,),
                "original arrival reused for a different admission",
            )
            db.commit()
            return admission
        db.execute(
            "INSERT INTO admissions VALUES (?,?,?,?,?,?, 'ready')",
            (
                admission,
                args.arrival,
                arrival["sequence"],
                request_sha,
                data.canonical(request),
                data.canonical(binding),
            ),
        )
        db.executemany(
            "INSERT INTO used VALUES (?,?,?)",
            [
                (kind, key, admission)
                for kind, key in intake_keys(record, arrival, tokens[0])
            ],
        )
        db.commit()
        return admission


def sync_dir(folder):
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def release(home, admission):
    """A process-bound kernel lease permits recovery after a publishing worker exits."""
    import fcntl

    digest_field(admission)
    with contextlib.closing(open_database(home)) as db:
        config = json.loads(db.execute("SELECT value FROM settings").fetchone()[0])
        require_engineering_scope(config["scope"])
        stored = db.execute(
            "SELECT binding FROM admissions WHERE id=?", (admission,)
        ).fetchone()
        require(stored is not None, "admission does not exist")
        require_engineering_scope(json.loads(stored[0])["release"]["scope"])
        with (home / (admission + ".lock")).open("ab") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            row = db.execute(
                "SELECT request_sha,request_json,binding,state FROM admissions WHERE id=?",
                (admission,),
            ).fetchone()
            require(row is not None, "admission does not exist")
            request_sha, request, binding_bytes, state = row
            binding = json.loads(binding_bytes)
            require_engineering_scope(binding["release"]["scope"])
            require(
                binding["release"]["scope"] == config["scope"],
                "retained release scope differs from intake settings",
            )
            original_request = json.loads(request)
            require(
                data.digest(binding) == admission
                and data.digest(original_request) == request_sha
                and binding["release"]["request_sha256"] == request_sha,
                "retained admission changed",
            )
            if (
                config["scope"] == "owner_intake"
                and "paired_source_exposure" in original_request["candidate"]
            ):
                pinned = binding["release"].get("source_retention_sha256")
                require(
                    pinned
                    and binding["release"]["scope"] == config["scope"]
                    and pinned == binding["anchor"].get("source_retention_sha256")
                    and binding["anchor"] == config["anchor"],
                    "original admission lacks a qualified source retention commitment; inspect any prior delivery as historical only",
                )
                digest_field(pinned)
            receipt = {**binding["release"], "admission_sha256": admission}
            files = {
                "paired.json": request + b"\n",
                "release.json": data.canonical(receipt) + b"\n",
            }
            target = home / admission
            if state == "ready":
                db.execute(
                    "UPDATE admissions SET state='publishing' WHERE id=?", (admission,)
                )
            if not target.exists():
                require(
                    state != "released",
                    "a released request is missing; reconcile original delivery",
                )
                with tempfile.TemporaryDirectory(dir=home) as stage:
                    staged = Path(stage) / "complete"
                    staged.mkdir(mode=0o700)
                    for name, contents in files.items():
                        with (staged / name).open("xb") as out:
                            os.fchmod(out.fileno(), 0o600)
                            out.write(contents)
                            out.flush()
                            os.fsync(out.fileno())
                    sync_dir(staged)
                    os.rename(staged, target)
            # A worker may have died between atomic publication and marking the ledger.
            for name, contents in files.items():
                require(
                    (target / name).read_bytes() == contents,
                    "published delivery differs",
                )
            sync_dir(home)
            db.execute(
                "UPDATE admissions SET state='released' WHERE id=?", (admission,)
            )
            return receipt


def people_status(home, admission):
    with contextlib.closing(open_database(home)) as db:
        row = db.execute(
            "SELECT binding,state FROM admissions WHERE id=?",
            (digest_field(admission),),
        ).fetchone()
        require(row is not None, "admission does not exist")
        binding = json.loads(row[0])
        require(data.digest(binding) == admission, "retained admission changed")
        return dict(
            admission_sha256=admission,
            state=row[1],
            retained_enrollment_binding_present="enrollment" in binding,
            original_enrollment_bindings_checked=False,
            site_attested_distinct_people=False,
            original_turn_consent_verified=False,
            production_authorization_available=False,
            scope=binding["release"]["scope"],
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("home", type=Path)
    actions = parser.add_subparsers(dest="op", required=True)
    init = actions.add_parser("install")
    init.add_argument("snapshot", type=Path)
    init.add_argument("study")
    init.add_argument("freeze")
    init.add_argument("inbox", type=Path)
    init.add_argument("native", type=Path)
    init.add_argument("native_sha256")
    init.add_argument(
        "--source-retention",
        type=Path,
        help="new enrolled A retention report if stored separately from FROZEN.json",
    )
    init.add_argument(
        "--scope", choices=("owner_intake", "engineering_fixture"), required=True
    )
    accept = actions.add_parser("admit")
    accept.add_argument("arrival")
    accept.add_argument("snapshot", type=Path)
    accept.add_argument("materials", type=Path)
    accept.add_argument("future", type=Path)
    accept.add_argument("root_pid")
    accept.add_argument("sqlite_home", type=Path)
    accept.add_argument("route", type=Path)
    accept.add_argument(
        "--source-retention",
        type=Path,
        help="original retention report if rechecking an older owner store",
    )
    accept.add_argument(
        "--training-run",
        type=Path,
        help="require original A/B enrolled-person records before admission",
    )
    actions.add_parser("release").add_argument("admission")
    actions.add_parser("people-status").add_argument("admission")
    args = parser.parse_args()
    if args.op == "install":
        install(args)
    elif args.op == "admit":
        print(admit(args))
    elif args.op == "release":
        print(json.dumps(release(args.home, args.admission), sort_keys=True))
    else:
        print(json.dumps(people_status(args.home, args.admission), sort_keys=True))


if __name__ == "__main__":
    main()
