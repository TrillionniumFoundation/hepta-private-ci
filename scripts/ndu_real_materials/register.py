"""Register real SROIE sources and five workflows without opening confirmation to actors."""

import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time

from PIL import Image
import pyarrow.parquet as pq

from .common import binding, digest, json_bytes, strict_json, write_json
from .evaluator import canonical, image_from_bytes
from .groups import allocate, connect_sources, normalized

FAMILIES = ("text_sufficient", "text_image_complementary", "selective_refinement",
            "preparation_required", "continuation_not_worthwhile")
OVERVIEW_EDGES = {"text_sufficient": 768, "text_image_complementary": 1024,
                  "selective_refinement": 768, "preparation_required": 192,
                  "continuation_not_worthwhile": 1024, "retention": 1024}


def png(image):
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def overview(image, edge):
    result = image.copy()
    result.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    return result


def target_boxes(row, field, width, height):
    expected = canonical(row["entities"][field], field)
    boxes = []
    if expected is None:
        return boxes
    for text, box in zip(row["words"], row["bboxes"]):
        candidates = [text.strip()]
        if field == "date":
            candidates += re.findall(r"\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})", text)
        else:
            candidates += re.findall(r"(?:RM\s*)?\d[\d,]*\.\d{2}", text.upper())
        if any(canonical(candidate, field) == expected for candidate in candidates):
            box = [int(value) for value in box]
            box = [max(0, min(width, box[0])), max(0, min(height, box[1])),
                   max(0, min(width, box[2])), max(0, min(height, box[3]))]
            if box[0] < box[2] and box[1] < box[3] and box not in boxes:
                boxes.append(box)
    return sorted(boxes, key=lambda box: ((box[2] - box[0]) * (box[3] - box[1]), box))


def load_sources(root):
    records, excluded = [], []
    image_root = root / "private" / "images"
    image_root.mkdir(exist_ok=False)
    for path in sorted((root / "private" / "upstream" / "data").glob("*.parquet")):
        for batch in pq.ParquetFile(path).iter_batches(batch_size=32):
            for row in batch.to_pylist():
                key = row["key"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                    raise ValueError("Unexpected upstream source key")
                raw = row["image"]["bytes"]
                preprocessing_started = time.perf_counter()
                with Image.open(io.BytesIO(raw)) as decoded:
                    if (decoded.format not in {"JPEG", "PNG", "WEBP"}
                            or getattr(decoded, "n_frames", 1) != 1
                            or decoded.width * decoded.height > 64_000_000):
                        raise ValueError("Original scan exceeds the separately bounded registration decoder")
                    image = decoded.convert("RGB")
                original_size = image.size
                canonical_raw = raw
                transform = {"operation": "identity", "original_size": original_size,
                             "canonical_size": original_size, "scale_x": 1.0, "scale_y": 1.0}
                original_path = image_root / (key + ".original.bin")
                with original_path.open("xb") as stream:
                    stream.write(raw)
                if image.width * image.height > 16_000_000:
                    scale = math.sqrt(16_000_000 / (image.width * image.height))
                    target_size = (int(image.width * scale), int(image.height * scale))
                    sx, sy = target_size[0] / image.width, target_size[1] / image.height
                    image = image.resize(target_size, Image.Resampling.LANCZOS)
                    row["bboxes"] = [[math.floor(box[0] * sx), math.floor(box[1] * sy),
                                      math.ceil(box[2] * sx), math.ceil(box[3] * sy)] for box in row["bboxes"]]
                    canonical_raw = png(image)
                    transform = {"operation": "lanczos_resize", "original_size": original_size,
                                 "canonical_size": target_size, "scale_x": sx, "scale_y": sy,
                                 "bbox_transform": "floor lower coordinates, ceil upper coordinates, then clamp"}
                source_path = image_root / (key + ".bin")
                with source_path.open("xb") as stream:
                    stream.write(canonical_raw)
                thumb = image.resize((9, 8)).convert("L")
                pixels = list(thumb.getdata())
                dhash = sum(int(pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
                            for y in range(8) for x in range(8))
                transcript = "\n".join(row["words"])
                field = "date" if int(hashlib.sha256(key.encode()).hexdigest(), 16) % 2 else "total"
                boxes = target_boxes(row, field, image.width, image.height)
                record = {"key": key, "entities": row["entities"], "words": row["words"],
                          "bboxes": row["bboxes"], "field": field, "target_boxes": boxes,
                          "image_sha256": digest(raw), "pixel_sha256": digest(image.tobytes()),
                          "source_image": binding(source_path, root),
                          "original_image": binding(original_path, root), "transform": transform,
                          "preprocessing_wall_seconds": time.perf_counter() - preprocessing_started,
                          "transcript_sha256": digest(transcript.encode()), "dhash": dhash,
                          "aspect": image.width / image.height, "word_tokens": set(normalized(w) for w in row["words"]),
                          "width": image.width, "height": image.height, "eligible": bool(boxes),
                          "upstream_partition": path.name.split("-")[0]}
                records.append(record)
                if not boxes:
                    excluded.append({"episode_group": key, "reason": "No source-annotated box matching the fixed selected field"})
    if len({row["key"] for row in records}) != len(records):
        raise ValueError("Upstream receipt keys are not unique")
    return records, excluded


def make_case(root, row, group, role, family, rubric_pin):
    identity = "case-" + digest(("sroie-v1:" + row["key"] + ":" + family).encode())[:24]
    sealed = role in {"confirmation", "retention_test"}
    parent = root / ("private/sealed" if sealed else "public") / role
    directory = parent / identity
    directory.mkdir(parents=True, exist_ok=False)
    image = image_from_bytes((root / row["source_image"]["path"]).read_bytes())
    small = overview(image, OVERVIEW_EDGES["retention" if role.startswith("retention") else family])
    (directory / "overview.png").write_bytes(png(small))
    field_name = "receipt date" if row["field"] == "date" else "total amount"
    wants_image = not (family == "text_sufficient" or role.startswith("retention"))
    prompt = "Return only the " + field_name + " shown in the receipt."
    if wants_image:
        prompt += " Also deliver a readable source-image crop containing an occurrence of that value."
    prompt += " Original image coordinates are supplied; a higher-resolution region may be requested if useful."
    public_text = "\n".join(row["words"]) if family == "text_sufficient" else ""
    initial_text, initial_image = None, None
    if family in {"selective_refinement", "continuation_not_worthwhile"}:
        initial_text = row["entities"][row["field"]]
        prompt += " The supplied text is already committed; preserve it."
    if family == "continuation_not_worthwhile":
        (directory / "initial.png").write_bytes(png(image.crop(row["target_boxes"][0])))
        initial_image = binding(directory / "initial.png", directory)
        initial_image.update(width=row["target_boxes"][0][2] - row["target_boxes"][0][0],
                             height=row["target_boxes"][0][3] - row["target_boxes"][0][1],
                             bbox=row["target_boxes"][0])
        prompt += " The supplied image is already committed; preserve its pixels."
    image_binding = binding(directory / "overview.png", directory)
    image_binding.update(width=small.width, height=small.height)
    packet = {"schema": "ndu.real.public-case.v1", "case_id": identity,
              "prompt": prompt, "public_text": public_text, "overview": image_binding,
              "source_size": {"width": image.width, "height": image.height},
              "initial_delivery": {"text": initial_text, "image": initial_image},
              "requirements": {"text": True, "image": wants_image},
              "action_contract": "ndu.real.receipt.actions.v1"}
    write_json(directory / "case.json", packet)
    (directory / "prompt.txt").write_text(prompt + "\n\n" + public_text + "\n")
    reference = {"schema": "ndu.real.receipt.reference.v1", "case_id": identity,
                 "source_group": group["source_group"], "episode_group": row["key"],
                 "role": role, "family": family, "field": row["field"],
                 "expected_text": row["entities"][row["field"]],
                 "target_boxes": row["target_boxes"], "source_image": row["source_image"],
                 "initial_commitment": {"text": initial_text, "image":
                     None if initial_image is None else binding(directory / "initial.png", root)},
                 "weights": {"text": 0.5, "image": 0.5} if wants_image else {"text": 1.0, "image": 0.0},
                 "rubric_sha256": rubric_pin, "constructed_handoff":
                     family in {"selective_refinement", "continuation_not_worthwhile"}}
    reference_path = root / "private" / "references" / (identity + ".json")
    write_json(reference_path, reference)
    return {"id": identity, "source_id": group["source_group"],
            "source_family": "SROIE_real_retail_receipts",
            "split": "retention" if role.startswith("retention") else role, "task_family": family,
            "text": binding(directory / "prompt.txt", root),
            "image": binding(directory / "overview.png", root),
            "reference": binding(reference_path, root),
            "packet": binding(directory / "case.json", root), "role": role,
            "episode_group": row["key"]}


def register(root, rubric):
    root, rubric = Path(root), Path(rubric)
    started = time.perf_counter()
    acquisition = strict_json((root / "acquisition.json").read_bytes())
    if acquisition["status"] != "Verified":
        raise ValueError("Source acquisition is incomplete")
    for row in acquisition["files"]:
        if digest((root / row["path"]).read_bytes()) != row["sha256"]:
            raise ValueError("Acquired source changed before registration")
    rubric_bytes = rubric.read_bytes()
    rubric_value = strict_json(rubric_bytes)
    if rubric_value["schema"] != "ndu.real.receipt.rubric.v1":
        raise ValueError("Unsupported evaluator rubric")
    (root / "rubric.json").write_bytes(rubric_bytes)
    rubric_pin = digest(rubric_bytes)
    records, excluded = load_sources(root)
    groups, edges = connect_sources(records)
    assignments = allocate(groups)
    (root / "private" / "sealed").mkdir(mode=0o700)
    cases, sources, index, catalog = [], [], {}, []
    counts, group_counts = Counter(), Counter()
    for group in groups:
        role = assignments[group["source_group"]]
        group_cases = []
        for row in group["members"]:
            if not row["eligible"]:
                continue
            families = ("text_image_complementary",) if role.startswith("retention") else FAMILIES
            for family in families:
                case = make_case(root, row, group, role, family, rubric_pin)
                group_cases.append(case)
                index[case["id"]] = case["reference"]
                catalog.append({key: case[key] for key in
                    ("id", "source_id", "role", "task_family", "packet", "reference", "episode_group")})
                counts[role] += 1
        if group_cases:
            group_counts[role] += 1
        evidence = {"schema": "ndu.real.source-evidence.v1", "source_group": group["source_group"],
                    "repository": acquisition["repository"], "revision": acquisition["revision"],
                    "license": "CC-BY-4.0", "episode_groups": sorted(row["key"] for row in group["members"]),
                    "image_sha256s": sorted({row["image_sha256"] for row in group["members"]}),
                    "canonical_sources": [{"episode_group": row["key"], "original": row["original_image"],
                                           "canonical": row["source_image"], "transform": row["transform"]}
                                          for row in group["members"]],
                    "grouping": "merchant identity/name variants, common address, exact/near duplicate graph",
                    "experiment_role": role, "foundation_pretraining_exposure": "UNKNOWN",
                    "public_example_previously_disclosed": group["previously_disclosed"]}
        evidence_path = root / "private" / "sources" / (group["source_group"] + ".json")
        write_json(evidence_path, evidence)
        evidence_binding = binding(evidence_path, root)
        for case in group_cases:
            cases.append({**{key: value for key, value in case.items()
                             if key not in {"packet", "role", "episode_group"}},
                          "source_evidence": evidence_binding})
        sources.append({"source_id": group["source_group"], "source_family": "SROIE_real_retail_receipts",
                        "allowed_split": "retention" if role.startswith("retention") else role,
                        "text_sha256s": sorted({case["text"]["sha256"] for case in group_cases} |
                                              {row["transcript_sha256"] for row in group["members"]}),
                        "image_sha256s": sorted({case["image"]["sha256"] for case in group_cases} |
                                               {row["image_sha256"] for row in group["members"]}),
                        "source_evidence_sha256": evidence_binding["sha256"],
                        "used_in_training": False, "previously_observed": group["previously_disclosed"],
                        "case_bindings": [{"case_id": case["id"], "task_family": case["task_family"],
                                           "text_sha256": case["text"]["sha256"],
                                           "image_sha256": case["image"]["sha256"],
                                           "reference_sha256": case["reference"]["sha256"]} for case in group_cases]})
    roles_by_image = defaultdict(set)
    for case in cases:
        roles_by_image[case["image"]["sha256"]].add(case["split"])
    if any(len(roles) != 1 for roles in roles_by_image.values()):
        raise ValueError("A public image crosses split boundaries")
    write_json(root / "source-registry.json", {"schema": "hepta.source-use-registry.v2", "sources": sources})
    registry_pin = digest((root / "source-registry.json").read_bytes())
    write_json(root / "material-manifest.template.json",
               {"schema": "hepta.text-image-materials.v1", "experiment_id": "ndu-real-sroie-20261107",
                "registry_sha256": registry_pin, "cases": cases, "models": []})
    write_json(root / "private" / "reference-index.v2.json",
               {"schema": "ndu.real.reference-index.v2", "rubric": binding(root / "rubric.json", root),
                "cases": index, "case_roles": {case["id"]: case["role"] for case in catalog}})
    write_json(root / "private" / "case-catalog.json", {"cases": catalog})
    write_json(root / "private" / "grouping.json", {"edges": edges, "assignments": assignments,
               "exclusions": excluded, "pretraining_exposure": "UNKNOWN"})
    write_json(root / "preprocessing-costs.json", {"schema": "ndu.real.preprocessing-costs.v1",
               "items": [{"episode_group": row["key"], "operation": row["transform"]["operation"],
                          "wall_seconds": row["preprocessing_wall_seconds"]} for row in records],
               "scope": "Dataset acquisition/registration, not actor deployment inference"})
    reference_pin = digest((root / "private" / "reference-index.v2.json").read_bytes())
    result = {"schema": "ndu.real.registration.v1", "repository": acquisition["repository"],
              "revision": acquisition["revision"], "original_receipts": len(records),
              "eligible_receipts": sum(row["eligible"] for row in records),
              "excluded_receipts": len(excluded), "merchant_groups": len(groups),
              "case_counts": dict(counts), "source_group_counts": dict(group_counts),
              "registry_sha256": registry_pin, "reference_index_sha256": reference_pin,
              "reference_index_path": "private/reference-index.v2.json",
              "rubric_sha256": rubric_pin, "grouping_sha256": digest((root / "private/grouping.json").read_bytes()),
              "confirmation_actor_reads": 0, "confirmation_evaluations": 0,
              "retention_test_actor_reads": 0, "retention_test_evaluations": 0,
              "model_materials": "REQUIRED_NOT_YET_BOUND", "foundation_pretraining_exposure": "UNKNOWN",
              "real_task_scope": "Five predeclared workflows on real receipt scans in one domain",
              "wall_seconds": time.perf_counter() - started, "scientific_admission": "HOLD"}
    write_json(root / "registration.json", result)
    # Export only disclosed train/development catalog entries; neither references nor other cases enter actor packets.
    write_json(root / "pilot-catalog.json", {"cases": [case for case in catalog if case["role"] in
               {"train", "development", "retention_validation"}]})
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, required=True)
    args = parser.parse_args()
    register(args.root, args.rubric)
