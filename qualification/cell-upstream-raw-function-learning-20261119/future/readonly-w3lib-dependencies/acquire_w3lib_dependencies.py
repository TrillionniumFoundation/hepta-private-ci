"""Retain original declared test dependencies without installation or imports."""

import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import platform
import signal
import stat
import sys
import time
import traceback
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(
    "/home/qian-qi/work/hepta-upstream-raw-function-learning-20261119-2e9b/future-dependencies-hypothesis-1"
)
OUT = ROOT / "bundle-1"
CHOICES = (
    (
        "hypothesis",
        "6.168.3",
        "pinned-metadata-1",
        "hypothesis-6.168.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
    ),
    (
        "frostwork",
        "0.2.2",
        "pinned-metadata-1",
        "frostwork-0.2.2-cp310-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
    ),
    (
        "sortedcontainers",
        "2.4.0",
        "transitive-metadata-1",
        "sortedcontainers-2.4.0-py2.py3-none-any.whl",
    ),
    (
        "typing_extensions",
        "4.13.2",
        "transitive-metadata-1",
        "typing_extensions-4.13.2-py3-none-any.whl",
    ),
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    raw = (
        value
        if isinstance(value, bytes)
        else (json.dumps(value, sort_keys=True) + "\n").encode()
    )
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return sha(raw)


def alarm(signum, frame):
    raise TimeoutError("bounded individual dependency acquisition exceeded 90 seconds")


def fetch(row):
    url = row["url"]
    if (
        urllib.parse.urlparse(url).scheme != "https"
        or urllib.parse.urlparse(url).hostname != "files.pythonhosted.org"
    ):
        raise ValueError("artifact URL is not the observed official PyPI host")
    started, cpu = time.perf_counter(), time.process_time()
    signal.alarm(90)
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                url, headers={"User-Agent": "Hepta-original-research-material/1.0"}
            ),
            timeout=30,
        ) as response:
            raw = response.read(8000001)
            receipt = {
                "url": url,
                "final_url": response.url,
                "http_status": response.status,
            }
        if (
            len(raw) > 8000000
            or len(raw) != row["size"]
            or sha(raw) != row["digests"]["sha256"]
        ):
            raise ValueError("original PyPI artifact length or SHA differs")
        receipt.update(
            bytes=len(raw),
            sha256=sha(raw),
            wall_seconds=time.perf_counter() - started,
            self_cpu_seconds=time.process_time() - cpu,
            finished_at_ns=str(time.time_ns()),
        )
        write(OUT / row["filename"], raw)
        write(OUT / (row["filename"] + ".HTTP.json"), receipt)
        return raw, receipt
    finally:
        signal.alarm(0)


def extract(raw, filename, site):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        if len(entries) > 5000 or sum(entry.file_size for entry in entries) > 40000000:
            raise ValueError("wheel expanded inventory exceeds the acquisition bound")
        names = [entry.filename for entry in entries]
        if len(set(names)) != len(names):
            raise ValueError("duplicate original wheel entry")
        record_names = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(record_names) != 1:
            raise ValueError("one original wheel RECORD is required")
        record_name = record_names[0]
        records = list(csv.reader(io.StringIO(archive.read(record_name).decode())))
        if {row[0] for row in records} != set(names) or len(records) != len(names):
            raise ValueError("wheel RECORD does not exactly cover the retained files")
        lookup = {row[0]: row for row in records}
        rows = []
        for entry in entries:
            path = Path(entry.filename)
            mode = entry.external_attr >> 16
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.suffix == ".pth"
                or stat.S_ISLNK(mode)
            ):
                raise ValueError("unsafe or executable-install-hook wheel path")
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError("nonregular wheel material")
            data = archive.read(entry)
            declared = lookup[entry.filename]
            if entry.filename != record_name:
                expected = "sha256=" + base64.urlsafe_b64encode(
                    hashlib.sha256(data).digest()
                ).decode().rstrip("=")
                if declared[1] != expected or int(declared[2]) != len(data):
                    raise ValueError("original wheel RECORD hash or size differs")
            elif declared[1:] != ["", ""]:
                raise ValueError("unexpected self-hash in wheel RECORD")
            target = site / path
            target.parent.mkdir(parents=True, exist_ok=True)
            write(target, data)
            rows.append(
                {
                    "path": str(path),
                    "bytes": len(data),
                    "sha256": sha(data),
                    "original_wheel": filename,
                    "original_RECORD_hash_verified": entry.filename != record_name,
                }
            )
        return rows


def main():
    if sys.version_info[:2] != (3, 12) or platform.machine() != "x86_64":
        raise ValueError(
            "the frozen original wheel ABI selection targets this CPython 3.12 x86_64 host"
        )
    OUT.mkdir(exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    selected = []
    for name, version, directory, filename in CHOICES:
        metadata_path = ROOT / directory / (name + "-PYPI.json")
        receipt = json.loads((ROOT / directory / (name + "-RECEIPT.json")).read_bytes())
        metadata_raw = metadata_path.read_bytes()
        if sha(metadata_raw) != receipt["sha256"] or receipt["status"] != "ACQUIRED":
            raise ValueError("original acquired dependency metadata changed")
        metadata = json.loads(metadata_raw)
        if metadata["info"]["version"] != version:
            raise ValueError("original dependency version differs")
        candidates = [
            row
            for row in metadata["urls"]
            if row["filename"] == filename and not row["yanked"]
        ]
        if len(candidates) != 1:
            raise ValueError("frozen official wheel choice is not unique")
        sdists = [
            row
            for row in metadata["urls"]
            if row["packagetype"] == "sdist" and not row["yanked"]
        ]
        if len(sdists) != 1:
            raise ValueError("one original source distribution is required")
        selected.append(
            {
                "name": name,
                "version": version,
                "metadata_path": str(metadata_path),
                "metadata_sha256": sha(metadata_raw),
                "wheel": candidates[0],
                "sdist": sdists[0],
                "requires_dist": metadata["info"].get("requires_dist"),
                "license_expression": metadata["info"].get("license_expression"),
                "license": metadata["info"].get("license"),
            }
        )
    write(
        OUT / "INTENT.json",
        {
            "selected": selected,
            "started_at_ns": str(time.time_ns()),
            "basis": "Original w3lib tox pin hypothesis6.168.3; original min runtime frostwork0.2.2; their declared sortedcontainers and typing-extensions requirements.",
            "new_model_calls": 0,
            "new_native_children": 0,
            "install_hooks_executed": False,
            "native_venv_modified": False,
            "maximum_individual_download_bytes": 8000000,
            "all_original_source_distributions_retained_unexecuted": True,
        },
    )
    site = OUT / "site"
    site.mkdir()
    files, acquisitions = [], []
    for package in selected:
        raw, receipt = fetch(package["wheel"])
        acquisitions.append(receipt)
        files.extend(extract(raw, package["wheel"]["filename"], site))
        _, receipt = fetch(package["sdist"])
        acquisitions.append(receipt)
    result = {
        "schema": "hepta.readonly-declared-test-dependencies.v1",
        "directory": str(site),
        "packages": selected,
        "files": sorted(files, key=lambda row: row["path"]),
        "wheel_RECORD_hashes_verified": True,
        "old_venv_modified": False,
        "install_hooks_executed": False,
        "packages_imported_outside_sandbox": False,
        "original_source_archives_retained": True,
        "new_model_calls": 0,
        "new_native_children": 0,
        "http_body_bytes_observed": sum(row["bytes"] for row in acquisitions),
        "total_network_bytes_unknown": True,
        "wall_seconds": time.perf_counter() - started,
        "self_cpu_seconds": time.process_time() - cpu,
        "completed_at_ns": str(time.time_ns()),
        "source_sha256": sha(Path(__file__).read_bytes()),
    }
    digest = write(OUT / "BUNDLE.json", result)
    print(
        json.dumps(
            {
                "path": str(OUT / "BUNDLE.json"),
                "sha256": digest,
                "files": len(files),
                "http_body_bytes_observed": result["http_body_bytes_observed"],
                "wall_seconds": result["wall_seconds"],
                "status": "RETAINED_PENDING_LICENSE_REVIEW",
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, alarm)
    try:
        main()
    except BaseException as error:
        if OUT.is_dir():
            write(
                OUT / "FAILED.json",
                {
                    "error_type": type(error).__name__,
                    "reason": str(error),
                    "traceback": traceback.format_exc(),
                    "observed_at_ns": str(time.time_ns()),
                    "partial_original_files_retained": True,
                    "new_model_calls": 0,
                    "new_native_children": 0,
                },
            )
        raise
