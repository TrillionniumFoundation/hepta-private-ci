"""Prepare a source-bound, arm-free development material review packet.

This creates work for an independent reviewer; it does not supply that reviewer
or certify a task family. Originals and the private identity map stay private.
"""

import hashlib
import json
from pathlib import Path
import secrets
import time

from .materials import _read, _strict_json, check_file
from .source_pool import admit_candidate_pool
from .state import sha256_value


RUBRIC = {
    "text_sufficient": "The original public text alone completes the real task; do not insert a reference answer into the input.",
    "text_image_complementary": "The original question and actual pixels jointly determine the requested output; certify neither from a family label.",
    "selective_refinement": "Supply an actual initial text/image output pair, an independent quality judgment for each, and a correction that preserves the adequate output.",
    "preparation_required": "Supply actual preparation/continuation traces, a task dependency, and independent endpoint grades showing no immediate preparation benefit.",
    "continuation_not_worthwhile": "Supply registered marginal-gain and full-cost evidence under the same external objective; an unanswerable image alone is insufficient.",
    "retention": "Supply the incumbent's previously registered capability, source-group-disjoint old tasks, and a predeclared noninferiority margin.",
}


def _write(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    return {
        "path": relative,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def _json_bytes(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode()


def build_review_packet(
    pool_root, output_root, *, expected_manifest_sha256, expected_history_sha256
):
    """Copy only current public inputs, with a separate source/role/reference map.

    All selected sources must already be train/development. Blinding concerns
    packet fields and filenames only; raw image pixels/metadata may identify a
    source. This is not an OS isolation or reviewer-independence certificate.
    """
    started = time.process_time(), time.perf_counter()
    pool_root, output_root = Path(pool_root), Path(output_root)
    raw, manifest_sha, _ = _read(pool_root, "CANDIDATES.json", 8 * 1024**2)
    if manifest_sha != sha256_value(expected_manifest_sha256, "external manifest pin"):
        raise ValueError("Candidate manifest differs from its external pin")
    manifest = _strict_json(raw)
    if not manifest.get("cases") or any(
        c["project_split"] not in {"train", "development"} for c in manifest["cases"]
    ):
        raise ValueError(
            "Development review cannot expose confirmation/retention sources"
        )
    admission = admit_candidate_pool(
        pool_root,
        "CANDIDATES.json",
        "HISTORY.json",
        expected_history_sha256=expected_history_sha256,
    )
    if output_root.resolve().is_relative_to(pool_root.resolve()):
        raise ValueError("Review output must not mutate the source pool")
    output_root.mkdir(parents=True, exist_ok=False)
    public, private, bindings, seen = [], [], [], set()
    for case in manifest["cases"]:
        blind_id = secrets.token_hex(16)
        while blind_id in seen:
            blind_id = secrets.token_hex(16)
        seen.add(blind_id)
        row = {"blind_id": blind_id}
        for field, suffix, limit in (
            ("text", ".txt", 1024**2),
            ("image", Path(case["image"]["path"]).suffix, 32 * 1024**2),
        ):
            data = check_file(pool_root, case[field], limit=limit)
            binding = _write(output_root, f"public/{blind_id}{suffix}", data)
            bindings.append(binding)
            row[field] = {**binding, "path": Path(binding["path"]).name}
        public.append(row)
        private.append(
            {
                "blind_id": blind_id,
                "case_id": case["id"],
                "project_split": case["project_split"],
                "source_group_id": case["source_group_id"],
                "episode_group_id": case["episode_group_id"],
                "reference": case["reference"],
                "upstream_grouping_complete": case["upstream_grouping_complete"],
                "task_family": None,
                "retention_capability": None,
            }
        )
    # Sorting random identifiers avoids retaining source or arm order in the view.
    public.sort(key=lambda row: row["blind_id"])
    packet = {
        "schema": "hepta.development-material-review-public.v1",
        "scope": "material_eligibility_review_only",
        "attribution": "VizWiz-VQA, https://vizwiz.org/tasks-and-datasets/vqa/, CC BY 4.0; original public question/image bytes are unchanged.",
        "review_questions": RUBRIC,
        "cases": public,
        "reviewer_assigned": False,
        "completed_reviews": 0,
    }
    public_binding = _write(output_root, "public/PACKET.json", _json_bytes(packet))
    private_binding = _write(
        output_root,
        "private/IDENTITY_MAP.json",
        _json_bytes(
            {
                "schema": "hepta.development-material-review-private.v1",
                "manifest_sha256": manifest_sha,
                "history_sha256": expected_history_sha256,
                "public_packet_sha256": public_binding["sha256"],
                "cases": private,
            }
        ),
    )
    result = {
        "schema": "hepta.development-material-review-preparation.v1",
        "manifest_sha256": manifest_sha,
        "history_sha256": expected_history_sha256,
        "public_packet": public_binding,
        "private_identity_map": private_binding,
        "public_input_files": bindings,
        "case_counts": admission["case_counts"],
        "new_original_materials": 0,
        "new_http_body_bytes": 0,
        "source_bytes_unchanged": True,
        "references_copied_to_public_packet": False,
        "source_roles_in_public_packet": False,
        "arm_or_model_identity_in_public_packet": False,
        "blinding_scope": "public JSON keys, randomized filenames and order; pixels/metadata may identify sources",
        "independent_reviewer_assigned": False,
        "completed_independent_reviews": 0,
        "independent_cluster_count": None,
        "verified_task_families": [],
        "registered_retention_cases": 0,
        "scientific_admission": False,
        "research_status": "HOLD",
        "cpu_seconds": time.process_time() - started[0],
        "wall_seconds": time.perf_counter() - started[1],
        "cost_scope": "inclusive packet preparation; admission/file verification are nested",
        "unknown_costs": ["energy", "charges", "outer process and final receipt write"],
    }
    _write(output_root, "PREPARATION.json", _json_bytes(result))
    return result
