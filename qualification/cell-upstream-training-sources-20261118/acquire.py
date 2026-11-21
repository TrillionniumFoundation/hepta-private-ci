"""Fetch pinned public Git blobs and install only isolated replay dependencies."""

import concurrent.futures, hashlib, json, os, pathlib, subprocess, sys, time, urllib.request


def write_json(path, value):
    with path.open("xb") as f:
        f.write(json.dumps(value, sort_keys=True, indent=2).encode() + b"\n")
        f.flush()
        os.fsync(f.fileno())


def main(payload):
    root = pathlib.Path(payload["root"])
    root.mkdir(exist_ok=False)
    started = time.perf_counter()
    for name, text in payload["published_files"].items():
        (root / name).write_bytes(text.encode())
    (root / "acquire.py").write_text(payload["acquire_source"])
    raw_meta = root / "upstream-api"
    raw_meta.mkdir()
    for name, text in payload["metadata"].items():
        (raw_meta / name).write_bytes(text.encode())
    write_json(
        root / "SOURCE_DEPLOYMENT.json",
        {
            "intent_commit": payload["intent_commit"],
            "acquire_sha256": hashlib.sha256(
                payload["acquire_source"].encode()
            ).hexdigest(),
            "new_model_calls": 0,
            "new_training_updates": 0,
        },
    )
    blobs = root / "git-blobs"
    blobs.mkdir()
    wanted = {}
    for entry in payload["sources"]["sources"]:
        for item in entry["source_files"]:
            for version, revision_key in (
                ("before", "before_commit"),
                ("after", "after_commit"),
            ):
                expected = item[version]
                wanted.setdefault(
                    expected["git_blob_sha1"],
                    {
                        "git_blob_sha1": expected["git_blob_sha1"],
                        "bytes": expected["bytes"],
                        "url": "https://raw.githubusercontent.com/"
                        + entry["project_id"]
                        + "/"
                        + entry[revision_key]
                        + "/"
                        + item["path"],
                    },
                )

    def fetch(entry):
        request = urllib.request.Request(
            entry["url"], headers={"User-Agent": "hepta-source-intake/1"}
        )
        before = time.perf_counter()
        with urllib.request.urlopen(request, timeout=40) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        assert len(raw) == entry["bytes"], entry["url"]
        git = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        assert git == entry["git_blob_sha1"], entry["url"]
        (blobs / git).write_bytes(raw)
        return {
            **entry,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "wall_seconds": time.perf_counter() - before,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        downloaded = list(executor.map(fetch, wanted.values()))
    identities = {entry["git_blob_sha1"]: entry for entry in downloaded}
    for entry in payload["sources"]["sources"]:
        short = entry["project_id"].split("/")[-1]
        for version in ("before", "after"):
            for item in entry["source_files"]:
                target = root / "repositories" / short / version / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = (blobs / item[version]["git_blob_sha1"]).read_bytes()
                with target.open("xb") as f:
                    f.write(raw)
                item[version]["sha256"] = hashlib.sha256(raw).hexdigest()
        license_file = (
            root / "repositories" / short / "after" / entry["license"]["path"]
        )
        assert (
            hashlib.sha256(license_file.read_bytes()).hexdigest()
            == entry["license"]["sha256"]
        )
    write_json(root / "BLOBS.json", downloaded)
    write_json(root / "SOURCES.json", payload["sources"])
    environment = root / "environment"
    environment.mkdir()
    dependencies = []
    for name in ("pytest", "freezegun", "pytest-timeout"):
        with urllib.request.urlopen(
            "https://pypi.org/pypi/" + name + "/json", timeout=30
        ) as response:
            raw = response.read(4 * 1024 * 1024)
        (environment / (name + ".pypi.json")).write_bytes(raw)
        parsed = json.loads(raw)
        dependencies.append(name + "==" + parsed["info"]["version"])
    write_json(environment / "DIRECT_REQUIREMENTS.json", dependencies)
    owned = root / "owned-setup-1"
    owned.mkdir()
    commands = [
        ["/usr/bin/python3", "-m", "venv", str(root / "venv")],
        [
            str(root / "venv/bin/python"),
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "--cache-dir",
            str(root / "pip-cache"),
            "download",
            "--only-binary=:all:",
            "--dest",
            str(root / "wheels"),
            *dependencies,
        ],
        [
            str(root / "venv/bin/python"),
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "install",
            "--no-index",
            "--find-links",
            str(root / "wheels"),
            *dependencies,
        ],
    ]
    stages = []
    for index, command in enumerate(commands):
        then = time.perf_counter()
        with (
            (owned / (str(index) + ".stdout")).open("xb") as out,
            (owned / (str(index) + ".stderr")).open("xb") as err,
        ):
            child = subprocess.Popen(command, stdout=out, stderr=err)
            try:
                code = child.wait(timeout=240)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    code = child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    code = child.wait(timeout=15)
                write_json(
                    owned / (str(index) + ".timeout.json"),
                    {"timed_out": True, "wait_returncode": code},
                )
                raise
        stage = {
            "argv": command,
            "wait_returncode": code,
            "wall_seconds": time.perf_counter() - then,
        }
        write_json(owned / (str(index) + ".json"), stage)
        stages.append(stage)
        assert code == 0, stage
    freeze = subprocess.run(
        [str(root / "venv/bin/python"), "-m", "pip", "freeze", "--all"],
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout
    (environment / "pip-freeze.txt").write_bytes(freeze)
    wheels = {
        path.name: {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in (root / "wheels").iterdir()
    }
    write_json(environment / "WHEELS.json", wheels)
    report = {
        "status": "ACQUIRED",
        "sources": len(payload["sources"]["sources"]),
        "distinct_git_blobs": len(downloaded),
        "downloaded_blob_bytes": sum(row["bytes"] for row in downloaded),
        "sources_sha256": hashlib.sha256(
            (root / "SOURCES.json").read_bytes()
        ).hexdigest(),
        "new_model_calls": 0,
        "new_training_updates": 0,
        "new_test_calls": 0,
        "wall_seconds": time.perf_counter() - started,
        "stages": stages,
        "dependencies": dependencies,
        "full_system_cost_known": False,
    }
    write_json(root / "ACQUISITION.json", report)
    print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main(json.load(sys.stdin))
