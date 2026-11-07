"""Six prospective pilot-training records under the first acquisition's shared cap."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import resource
import shutil
import time
import zipfile

from . import acquire_vizwiz, materials, source_pool, state
from .acquire_vizwiz import (
    CAP,
    IMAGES,
    DownloadBudget,
    RangeArchive,
    binding,
    write_json,
)
from .materials import _decode_image, _strict_json
from .source_pool import HISTORY_SCHEMA, SCHEMA, admit_candidate_pool, pixel_digest


def extend(previous, output):
    started = time.process_time(), time.perf_counter()
    previous, root = Path(previous), Path(output)
    old_manifest = _strict_json((previous / "CANDIDATES.json").read_bytes())
    old_receipt = _strict_json((previous / "ACQUISITION_RECEIPT.json").read_bytes())
    old_history = _strict_json((previous / "HISTORY.json").read_bytes())
    if (
        old_receipt["status"] != "completed"
        or not 0 <= old_receipt["body_bytes_read"] < CAP
    ):
        raise ValueError(
            "Completed first acquisition with remaining shared budget required"
        )
    if len(old_manifest["cases"]) != 3 or any(
        c["project_split"] != "development" for c in old_manifest["cases"]
    ):
        raise ValueError(
            "This extension preserves the original three development roles"
        )
    admit_candidate_pool(
        previous,
        "CANDIDATES.json",
        "HISTORY.json",
        expected_history_sha256=old_manifest["history_sha256"],
    )
    shutil.copytree(previous, root)
    for name in (
        "CANDIDATES.json",
        "HISTORY.json",
        "ADMISSION.json",
        "ACQUISITION_PLAN.json",
        "ACQUISITION_RECEIPT.json",
        "DOWNLOAD_ATTEMPTS.jsonl",
    ):
        (root / name).rename(root / ("DEVELOPMENT_" + name))
    expected_images = [f"VizWiz_train_{i:08d}.jpg" for i in range(3, 9)]
    plan = {
        "schema": "hepta.vizwiz-pilot-training-extension.v1",
        "image_archive": IMAGES,
        "selection_rule": "next six image filenames after the three frozen development candidates; no answer/effect filter",
        "selected_images": expected_images,
        "project_split": "train",
        "upstream_split": "train",
        "prior_body_bytes_read": old_receipt["body_bytes_read"],
        "cumulative_body_byte_cap": CAP,
        "previous_candidate_manifest": binding(
            root, root / "DEVELOPMENT_CANDIDATES.json"
        ),
        "previous_acquisition_receipt": binding(
            root, root / "DEVELOPMENT_ACQUISITION_RECEIPT.json"
        ),
        "confirmation_acquisition": False,
        "family_assignment": None,
        "runtime_source_sha256": {
            Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in (
                __file__,
                acquire_vizwiz.__file__,
                materials.__file__,
                source_pool.__file__,
                state.__file__,
            )
        },
    }
    write_json(root / "ACQUISITION_PLAN.json", plan)
    download = DownloadBudget(root)
    download.bytes_read = old_receipt["body_bytes_read"]
    cases = list(old_manifest["cases"])
    status = "failed"
    try:
        with zipfile.ZipFile(root / "raw" / "Annotations.zip") as archive:
            info = next(
                i
                for i in archive.infolist()
                if PurePosixPath(i.filename).name == "train.json"
            )
            annotation_bytes = archive.read(info)
            records = _strict_json(annotation_bytes)
        selected = sorted(enumerate(records), key=lambda pair: pair[1]["image"])[3:9]
        if [record["image"] for _, record in selected] != expected_images:
            raise ValueError(
                "Upstream records differ from the prospective six-image plan"
            )
        provenance_template = _strict_json(
            (root / cases[0]["source_evidence"]["path"]).read_bytes()
        )
        remote = RangeArchive(download, IMAGES)
        with zipfile.ZipFile(remote) as archive:
            files = [i for i in archive.infolist() if not i.is_dir()]
            members = {PurePosixPath(i.filename).name: i for i in files}
            if len(members) != len(files):
                raise ValueError("Ambiguous archive member names")
            for index, record in selected:
                image_name = record["image"]
                info = members[image_name]
                if info.file_size > 32 * 1024**2:
                    raise ValueError("Source image exceeds material profile")
                folder = root / "data" / Path(image_name).stem
                folder.mkdir()
                image_bytes = archive.read(info)
                (folder / "input.jpg").write_bytes(image_bytes)
                (folder / "question.txt").write_text(
                    record["question"], encoding="utf-8"
                )
                write_json(folder / "reference.json", record)
                provenance = {
                    **provenance_template,
                    "annotation_record_index": index,
                    "image_archive_bytes": remote.size,
                    "image_archive_etag": remote.etag,
                    "image_member": info.filename,
                    "image_member_crc32": info.CRC,
                }
                write_json(folder / "provenance.json", provenance)
                identity = "vizwiz:" + image_name
                cases.append(
                    {
                        **cases[0],
                        "id": identity,
                        "source_id": identity,
                        "source_group_id": identity,
                        "episode_group_id": identity,
                        "derivative_root_ids": [identity],
                        "project_split": "train",
                        "text": binding(root, folder / "question.txt"),
                        "image": binding(root, folder / "input.jpg"),
                        "reference": binding(root, folder / "reference.json"),
                        "source_evidence": binding(root, folder / "provenance.json"),
                        "image_pixel_sha256": pixel_digest(_decode_image(image_bytes)),
                    }
                )
        status = "completed"
    finally:
        receipt = {
            "schema": "hepta.public-acquisition-extension-receipt.v1",
            "status": status,
            "plan": binding(root, root / "ACQUISITION_PLAN.json"),
            "attempts": download.receipts,
            "prior_receipt": binding(
                root, root / "DEVELOPMENT_ACQUISITION_RECEIPT.json"
            ),
            "prior_body_bytes_read": old_receipt["body_bytes_read"],
            "new_body_bytes_read": download.bytes_read - old_receipt["body_bytes_read"],
            "cumulative_body_bytes_read": download.bytes_read,
            "cumulative_body_byte_cap": CAP,
            "cpu_seconds": time.process_time() - started[0],
            "wall_seconds": time.perf_counter() - started[1],
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "scope": "inclusive extension including local copies, excluding final receipt/registry writes",
            "do_not_add_to_request_subcosts": True,
            "model_execution": False,
            "unknown_costs": [
                "process_startup",
                "final_receipt_and_registry_writes",
                "wire_bytes_including_headers_or_unread_buffers",
                "energy",
                "actual_charges",
            ],
        }
        write_json(root / "ACQUISITION_RECEIPT.json", receipt)
    history = {"schema": HISTORY_SCHEMA, "cases": old_history["cases"] + cases[3:]}
    write_json(root / "HISTORY.json", history)
    manifest = {
        "schema": SCHEMA,
        "study_id": "vizwiz-pilot-train-development-20261107",
        "history_sha256": binding(root, root / "HISTORY.json")["sha256"],
        "acquisition_plan": binding(root, root / "ACQUISITION_PLAN.json"),
        "acquisition_receipt": binding(root, root / "ACQUISITION_RECEIPT.json"),
        "cases": cases,
    }
    write_json(root / "CANDIDATES.json", manifest)
    admission = admit_candidate_pool(
        root,
        "CANDIDATES.json",
        "HISTORY.json",
        expected_history_sha256=manifest["history_sha256"],
    )
    write_json(root / "ADMISSION.json", admission)
    return {
        "output": str(root),
        "cumulative_body_bytes_read": download.bytes_read,
        "admission": admission,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(extend(args.previous, args.output), indent=2))
