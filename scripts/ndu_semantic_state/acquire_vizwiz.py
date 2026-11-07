"""Bounded official VizWiz train acquisition; no models, held-out set or family claims."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import resource
import time
import urllib.request
import uuid
import zipfile

from .materials import _decode_image, _strict_json
from . import materials, source_pool, state
from .source_pool import HISTORY_SCHEMA, SCHEMA, admit_candidate_pool, pixel_digest


PAGE = "https://vizwiz.org/tasks-and-datasets/vqa/"
ANNOTATIONS = "https://vizwiz.cs.colorado.edu/VizWiz_final/vqa_data/Annotations.zip"
IMAGES = "https://vizwiz.cs.colorado.edu/VizWiz_final/images/train.zip"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
CAP = 25 * 1024**2


def write_json(path, value):
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    )


def binding(root, path):
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


class DownloadBudget:
    def __init__(self, root):
        self.root, self.bytes_read, self.receipts = root, 0, []

    def fetch(self, url, *, head=False, span=None, etag=None):
        headers = {"User-Agent": "Hepta-source-admission/1.0"}
        if span is not None:
            if span[1] - span[0] + 1 > CAP - self.bytes_read:
                raise ValueError("Acquisition byte budget exhausted before request")
            headers["Range"] = f"bytes={span[0]}-{span[1]}"
        if etag:
            headers["If-Match"] = etag
        row = {
            "attempt_id": uuid.uuid4().hex,
            "url": url,
            "method": "HEAD" if head else "GET",
            "requested_range": span,
            "started_unix": time.time(),
            "status": "started",
            "bytes_read": 0,
        }
        start = time.process_time(), time.perf_counter()
        journal = self.root / "DOWNLOAD_ATTEMPTS.jsonl"
        with journal.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        data = bytearray()
        try:
            request = urllib.request.Request(url, headers=headers, method=row["method"])
            with urllib.request.urlopen(request, timeout=30) as response:
                row.update(
                    http_status=response.status,
                    final_url=response.url,
                    headers={
                        k.lower(): v
                        for k, v in response.headers.items()
                        if k.lower()
                        in {
                            "content-length",
                            "content-range",
                            "content-type",
                            "etag",
                            "last-modified",
                        }
                    },
                )
                if span is not None and (
                    response.status != 206
                    or not response.headers.get("Content-Range", "").startswith(
                        f"bytes {span[0]}-{span[1]}/"
                    )
                ):
                    raise ValueError(
                        "Server did not honor exact byte range; full archive download refused"
                    )
                if etag and response.headers.get("ETag") != etag:
                    raise ValueError("Archive ETag changed during range acquisition")
                declared = int(response.headers.get("Content-Length", "0"))
                if not head and declared > CAP - self.bytes_read:
                    raise ValueError("Response exceeds remaining acquisition budget")
                while not head:
                    remaining = CAP - self.bytes_read
                    if remaining <= 0:
                        raise ValueError("Acquisition byte budget exhausted")
                    block = response.read(min(65536, remaining))
                    if not block:
                        break
                    data.extend(block)
                    self.bytes_read += len(block)
                    row["bytes_read"] += len(block)
                if span is not None and len(data) != span[1] - span[0] + 1:
                    raise ValueError("Truncated range response")
                row.update(status="completed", sha256=hashlib.sha256(data).hexdigest())
        except Exception as error:
            row.update(
                status="failed",
                error={"type": type(error).__name__, "message": str(error)},
            )
            raise
        finally:
            row.update(
                finished_unix=time.time(),
                cpu_seconds=time.process_time() - start[0],
                wall_seconds=time.perf_counter() - start[1],
            )
            self.receipts.append(row)
            with journal.open("a") as stream:
                stream.write(json.dumps(row) + "\n")
        return bytes(data), row


class RangeArchive(io.RawIOBase):
    """Seekable ZIP64 source; only requested ranges consume the common budget."""

    def __init__(self, download, url):
        self.download, self.url, self.position = download, url, 0
        _, row = download.fetch(url, head=True)
        self.size = int(row["headers"]["content-length"])
        self.etag = row["headers"].get("etag")
        if not self.etag or self.etag.startswith("W/"):
            raise ValueError("Stable strong archive ETag required")

    def seek(self, offset, whence=0):
        value = offset + (
            0 if whence == 0 else self.position if whence == 1 else self.size
        )
        if value < 0 or value > self.size or whence not in (0, 1, 2):
            raise ValueError("Invalid archive seek")
        self.position = value
        return value

    def tell(self):
        return self.position

    def read(self, size=-1):
        size = min(self.size - self.position, size if size >= 0 else self.size)
        if not size:
            return b""
        data, _ = self.download.fetch(
            self.url, span=(self.position, self.position + size - 1), etag=self.etag
        )
        self.position += len(data)
        return data

    def seekable(self):
        return True


def acquire(output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    raw = root / "raw"
    raw.mkdir()
    started = time.process_time(), time.perf_counter()
    plan = {
        "schema": "hepta.vizwiz-candidate-acquisition.v1",
        "source_page": PAGE,
        "annotation_archive": ANNOTATIONS,
        "image_archive": IMAGES,
        "upstream_split": "train",
        "selector": {
            "order": "image_filename_ascending",
            "count": 3,
            "outcome_filter": None,
        },
        "project_split": "development",
        "body_byte_cap": CAP,
        "license": "CC-BY-4.0",
        "license_url": LICENSE,
        "family_assignment": None,
        "confirmation_acquisition": False,
        "source_group_rule": "upstream image identity; photographer/session independence unknown",
        "runtime_source_sha256": {
            Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in (
                __file__,
                materials.__file__,
                source_pool.__file__,
                state.__file__,
            )
        },
    }
    write_json(root / "ACQUISITION_PLAN.json", plan)
    download = DownloadBudget(root)
    status, cases = "failed", []
    try:
        for url, name in (
            (PAGE, "source-page.html"),
            (LICENSE, "license-page.html"),
            (ANNOTATIONS, "Annotations.zip"),
        ):
            data, _ = download.fetch(url)
            (raw / name).write_bytes(data)
        with zipfile.ZipFile(raw / "Annotations.zip") as archive:
            names = [
                i
                for i in archive.infolist()
                if PurePosixPath(i.filename).name == "train.json"
            ]
            if len(names) != 1 or names[0].file_size > 64 * 1024**2:
                raise ValueError(
                    "Unique bounded official train annotation member required"
                )
            annotation_bytes = archive.read(names[0])
            records = _strict_json(annotation_bytes)
            annotation_member = names[0].filename
        if not isinstance(records, list) or len({r["image"] for r in records}) != len(
            records
        ):
            raise ValueError("Unique upstream image identities required")
        selected = sorted(enumerate(records), key=lambda pair: pair[1]["image"])[:3]
        remote = RangeArchive(download, IMAGES)
        with zipfile.ZipFile(remote) as archive:
            files = [i for i in archive.infolist() if not i.is_dir()]
            members = {PurePosixPath(i.filename).name: i for i in files}
            if len(members) != len(files):
                raise ValueError("Ambiguous image archive member names")
            for index, record in selected:
                image_name = record["image"]
                if (
                    not image_name.startswith("VizWiz_train_")
                    or PurePosixPath(image_name).name != image_name
                ):
                    raise ValueError(
                        "Non-train or noncanonical upstream image identity"
                    )
                info = members[image_name]
                if info.file_size > 32 * 1024**2:
                    raise ValueError("Source image exceeds material profile")
                folder = root / "data" / Path(image_name).stem
                folder.mkdir(parents=True)
                image_bytes = archive.read(info)
                (folder / "input.jpg").write_bytes(image_bytes)
                (folder / "question.txt").write_text(
                    record["question"], encoding="utf-8"
                )
                write_json(folder / "reference.json", record)
                provenance = {
                    "provider": "VizWiz",
                    "source_page": PAGE,
                    "license": "CC-BY-4.0",
                    "license_url": LICENSE,
                    "attribution": "VizWiz dataset; Gurari et al., VizWiz Grand Challenge, CVPR 2018; official 2023 annotation release",
                    "annotation_archive": binding(root, raw / "Annotations.zip"),
                    "annotation_archive_url": ANNOTATIONS,
                    "annotation_member": annotation_member,
                    "annotation_member_sha256": hashlib.sha256(
                        annotation_bytes
                    ).hexdigest(),
                    "annotation_record_index": index,
                    "record_serialization": "Full original record reserialized as sorted UTF-8 JSON; no fields changed",
                    "image_archive_url": IMAGES,
                    "image_archive_bytes": remote.size,
                    "image_archive_etag": remote.etag,
                    "whole_image_archive_sha256": None,
                    "image_member": info.filename,
                    "image_member_crc32": info.CRC,
                    "source_page_bytes": binding(root, raw / "source-page.html"),
                    "license_page_bytes": binding(root, raw / "license-page.html"),
                    "request_origin": "Provider documents naturally occurring blind-user photo/question; answers are external crowdsourced annotations",
                    "independent_domain_relevance_verified": False,
                }
                write_json(folder / "provenance.json", provenance)
                identity = "vizwiz:" + image_name
                cases.append(
                    {
                        "id": identity,
                        "source_id": identity,
                        "source_group_id": identity,
                        "episode_group_id": identity,
                        "derivative_root_ids": [identity],
                        "group_evidence": "Upstream image identity; photographer and session IDs are unavailable, so independent clusters are not certified",
                        "upstream_grouping_complete": False,
                        "upstream_split": "train",
                        "project_split": "development",
                        "task_family": None,
                        "retention_capability": None,
                        "text": binding(root, folder / "question.txt"),
                        "image": binding(root, folder / "input.jpg"),
                        "reference": binding(root, folder / "reference.json"),
                        "source_evidence": binding(root, folder / "provenance.json"),
                        "image_pixel_sha256": pixel_digest(_decode_image(image_bytes)),
                        "used_in_project_training": False,
                        "observed_in_project": True,
                        "pretraining_exposure": "unknown",
                    }
                )
        status = "completed"
    finally:
        receipt = {
            "schema": "hepta.public-acquisition-receipt.v1",
            "status": status,
            "plan": binding(root, root / "ACQUISITION_PLAN.json"),
            "attempts": download.receipts,
            "body_bytes_read": download.bytes_read,
            "body_byte_cap": CAP,
            "cpu_seconds": time.process_time() - started[0],
            "wall_seconds": time.perf_counter() - started[1],
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "scope": "inclusive acquisition process function before final receipt/history/manifest writes",
            "do_not_add_to_request_subcosts": True,
            "unknown_costs": [
                "process_startup",
                "final_receipt_and_registry_writes",
                "wire_bytes_including_headers_or_unread_buffers",
                "energy",
                "actual_charges",
            ],
            "model_execution": False,
        }
        write_json(root / "ACQUISITION_RECEIPT.json", receipt)
    write_json(root / "HISTORY.json", {"schema": HISTORY_SCHEMA, "cases": cases})
    manifest = {
        "schema": SCHEMA,
        "study_id": "vizwiz-train-development-candidates-20261107",
        "history_sha256": binding(root, root / "HISTORY.json")["sha256"],
        "acquisition_plan": binding(root, root / "ACQUISITION_PLAN.json"),
        "acquisition_receipt": binding(root, root / "ACQUISITION_RECEIPT.json"),
        "cases": cases,
    }
    write_json(root / "CANDIDATES.json", manifest)
    result = admit_candidate_pool(
        root,
        "CANDIDATES.json",
        "HISTORY.json",
        expected_history_sha256=manifest["history_sha256"],
    )
    write_json(root / "ADMISSION.json", result)
    return {
        "output": str(root),
        "cases": len(cases),
        "body_bytes_read": download.bytes_read,
        "admission": result,
        "history_pin_authority": "local acquisition only; external owner not verified",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(acquire(args.output), indent=2))
