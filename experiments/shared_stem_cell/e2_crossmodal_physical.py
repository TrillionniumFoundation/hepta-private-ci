"""Research-only physical DINOv2 -> Granite -> train-only Bridge experiment.

PREPARE authors expressly synthetic image tasks with withheld FUTURE captions and
class labels in a different artifact. FIT-PREDICT never accepts future targets.
EVALUATE independently loads real Granite to embed future target captions.
The physical paths reuse the inherited strict model/feature/bridge owners.
No model ranking, production capability or genuine natural-image claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

CLASSES = ("red-square", "blue-circle", "green-triangle", "yellow-diamond")
SCHEMA = "hepta.e2.crossmodal-synthetic-physical.v1"
ARMS = ("fitted", "rotated_target_control", "unaligned_identity")
SOURCE_FILES = frozenset({"train_images.jsonl", "future_images.jsonl", "train_anchors.jsonl", "train_class.jsonl"})
TARGET_FILES = frozenset({"future_caption_targets.jsonl", "future_class_targets.jsonl"})


class GateError(ValueError):
    pass


def canon(obj):
    return (json.dumps(obj, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GateError("duplicate JSON key")
        result[key] = value
    return result


def get_json(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(GateError("nonfinite JSON")))


def put(path, raw):
    path = Path(path)
    if path.is_symlink() or not path.parent.is_dir() or path.exists():
        raise GateError("write-once output required")
    with path.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return sha(raw)


def rows(path):
    raw = Path(path).read_bytes()
    if not raw or not raw.endswith(b"\n") or len(raw) > 64_000_000:
        raise GateError("bad row file bounds")
    result = [json.loads(line, object_pairs_hook=unique) for line in raw.splitlines()]
    if not 1 <= len(result) <= 256 or any(canon(row).rstrip(b"\n") != line for row, line in zip(result, raw.splitlines())):
        raise GateError("noncanonical or excessive case rows")
    return result


def _describe(color, shape, idx, phase):
    # No row/case ID in captions; never reuses *literal* train anchors at future.
    train = (
        "a drawing of a %s %s on pale paper",
        "a %s-colored %s shape in the center",
        "a clearly outlined %s %s on a neutral background",
        "a simple %s %s geometric symbol",
    )
    future = (
        "a centered %s %s with a thin dark edge",
        "the central object is a %s %s on gray paper",
    )
    template = (train if phase == "train" else future)[idx]
    return template % (color, shape)


def _draw(root, case_id, color, shape, variant):
    from PIL import Image, ImageDraw
    c = {"red": (218, 54, 53), "blue": (45, 83, 212),
         "green": (41, 164, 81), "yellow": (238, 188, 39)}[color]
    image = Image.new("RGB", (96, 96), (235 - variant * 2, 234 - variant, 229 + variant))
    brush = ImageDraw.Draw(image)
    d = variant % 5
    if shape == "square":
        brush.rectangle((20 + d, 19 + d, 77 - d, 77 - d), fill=c, outline=(30, 30, 30), width=2)
    elif shape == "circle":
        brush.ellipse((19 + d, 20 + d, 77 - d, 77 - d), fill=c, outline=(30, 30, 30), width=2)
    elif shape == "triangle":
        brush.polygon([(48, 14 + d), (80 - d, 78 - d), (16 + d, 78 - d)], fill=c)
    elif shape == "diamond":
        brush.polygon([(48, 14 + d), (80 - d, 47), (48, 80 - d), (16 + d, 47)], fill=c)
    else:
        raise GateError("unrecognized synthetic shape")
    file = root / (case_id + ".png")
    if file.exists():
        raise GateError("duplicate image")
    image.save(file, format="PNG")
    return file, sha(file.read_bytes())


def prepare(root: Path):
    """Creates separate source/ vs withheld/ artifacts; all samples synthetic."""
    root.mkdir(parents=True, exist_ok=False)
    source, withheld = root / "source", root / "withheld"
    source.mkdir()
    withheld.mkdir()
    (source / "images").mkdir()
    train, future, anchors, classes, future_targets, future_class = [], [], [], [], [], []
    scope = "hepta-e2-physical-synthetic-only"
    for phase, n in (("train", 4), ("future", 2)):
        for ci, label in enumerate(CLASSES):
            color, shape = label.split("-")
            for i in range(n):
                index = ci * n + i
                cid = "synthetic-" + sha(canon(["e2.synthetic-case-id.v1", phase, ci, i]))[:20]
                file, img_sha = _draw(source / "images", cid, color, shape, index + (0 if phase == "train" else 11))
                group = "source-group-" + sha(canon(["e2.synthetic-source-group.v1", phase, ci, i]))[:20]
                when = 1 + index if phase == "train" else 100 + index
                condition = "vision_required"
                question = "Which color and shape is at the center of this image?"
                source_sha = sha(canon(["hepta.e2.image-case.v1", cid, group, scope, when,
                                        condition, img_sha, question]))
                record = {"case_id": cid, "group_id": group, "scope": scope,
                          "observed_at": when, "split": phase, "condition": condition,
                          "image_path": file.name, "image_sha256": img_sha,
                          "question": question, "source_sha256": source_sha}
                caption = _describe(color, shape, i, phase)
                if phase == "train":
                    train.append(record)
                    anchors.append({k: record[k] for k in ("case_id", "group_id", "scope", "observed_at", "source_sha256")}
                                   | {"target_text": caption})
                    classes.append({"case_id": cid, "class_label": label})
                else:
                    future.append(record)
                    future_targets.append({k: record[k] for k in ("case_id", "group_id", "scope", "observed_at")}
                                          | {"split": "future", "source_input_sha256": img_sha,
                                             "target_text": caption})
                    future_class.append({k: record[k] for k in ("case_id", "group_id", "scope", "observed_at", "source_sha256")}
                                        | {"source_input_sha256": img_sha, "class_label": label})
    source_files, target_files = {}, {}
    for path, payload in ((source / "train_images.jsonl", train),
                          (source / "future_images.jsonl", future),
                          (source / "train_anchors.jsonl", anchors),
                          (source / "train_class.jsonl", classes),
                          (withheld / "future_caption_targets.jsonl", future_targets),
                          (withheld / "future_class_targets.jsonl", future_class)):
        pin = put(path, b"".join(canon(x) for x in payload))
        (source_files if path.parent == source else target_files)[path.name] = pin
    if len(train) != 16 or len(future) != 8:
        raise GateError("wrong synthetic dataset size")
    for t in (train, future):
        if len({r["image_sha256"] for r in t}) != len(t):
            raise GateError("duplicated input image bytes")
    if {r["group_id"] for r in train} & {r["group_id"] for r in future}:
        raise GateError("train/future group leakage")
    if {r["target_text"] for r in anchors} & {r["target_text"] for r in future_targets}:
        raise GateError("literal train/future caption reuse")
    manifest = {"schema": SCHEMA + ".source-plan", "synthetic_data": True,
                "training_cases": len(train), "future_cases": len(future),
                "scope": scope, "file_sha256s": source_files, "production_accepted": False,
                "model_selection_permitted": False, "authority": "DENY_ALL"}
    source_pin = put(root / "source-manifest.json", canon(manifest))
    withheld_manifest = {"schema": SCHEMA + ".withheld-target-plan",
                         "synthetic_data": True, "source_manifest_sha256": source_pin,
                         "file_sha256s": target_files, "production_accepted": False,
                         "authority": "DENY_ALL"}
    put(withheld / "target-manifest.json", canon(withheld_manifest))
    return manifest


def _verify_split(source: Path, manifest: dict):
    if (set(manifest) != {"schema", "synthetic_data", "training_cases", "future_cases",
                          "scope", "file_sha256s", "production_accepted", "model_selection_permitted", "authority"}
        or manifest["schema"] != SCHEMA + ".source-plan" or manifest["synthetic_data"] is not True
        or manifest["training_cases"] != 16 or manifest["future_cases"] != 8
        or manifest["production_accepted"] is not False or manifest["model_selection_permitted"] is not False
        or manifest["authority"] != "DENY_ALL"
        or type(manifest["file_sha256s"]) is not dict
        or set(manifest["file_sha256s"]) != SOURCE_FILES):
        raise GateError("unsafe synthetic source manifest or exposed future target digest")
    for key in SOURCE_FILES:
        p = source / key
        if p.is_symlink() or not p.is_file() or sha(p.read_bytes()) != manifest["file_sha256s"][key]:
            raise GateError("source file was changed")
    train, future = rows(source / "train_images.jsonl"), rows(source / "future_images.jsonl")
    if {r["group_id"] for r in train} & {r["group_id"] for r in future}:
        raise GateError("training source leaked to future")
    if min(r["observed_at"] for r in future) <= max(r["observed_at"] for r in train):
        raise GateError("future chronological order violated")
    if {r["image_sha256"] for r in train} & {r["image_sha256"] for r in future}:
        raise GateError("future source image reused in training")
    return train, future


def _class_predictions(geometry: dict, training: list, class_map: list) -> dict:
    """Predict future class using only TRAIN labels and genuine training target vectors."""
    label_by_case = {}
    for row in class_map:
        if set(row) != {"case_id", "class_label"} or row["case_id"] in label_by_case or row["class_label"] not in CLASSES:
            raise GateError("invalid train class map")
        label_by_case[row["case_id"]] = row["class_label"]
    if {r["case_id"] for r in training} != set(label_by_case):
        raise GateError("training prototype target join mismatch")
    proto = {label: [] for label in CLASSES}
    for item in training:
        target = item["target"]
        if target["modality"] != "text" or len(target["values"]) != 384:
            raise GateError("bad real Granite target vector")
        proto[label_by_case[item["case_id"]]].append(target["values"])
    if any(len(v) != 4 for v in proto.values()):
        raise GateError("unequal or missing train prototype classes")
    centroids = {label: tuple(math.fsum(v[i] for v in vecs) / len(vecs) for i in range(384))
                 for label, vecs in proto.items()}

    def cosine(x, y):
        n1 = math.sqrt(math.fsum(z*z for z in x))
        n2 = math.sqrt(math.fsum(z*z for z in y))
        if n1 <= 0 or n2 <= 0:
            raise GateError("degenerate geometry")
        return math.fsum(a*b for a, b in zip(x,y)) / (n1*n2)

    result=[]
    for item in geometry["predictions"]:
        answers = {}
        for arm in ARMS:
            vec = item["predictions"][arm]
            if len(vec) != 384:
                raise GateError("candidate feature width drift")
            answers[arm] = max(CLASSES, key=lambda label: (cosine(vec, centroids[label]), -CLASSES.index(label)))
        result.append({"case_id": item["case_id"], "group_id": item["group_id"],
                       "scope": item["scope"], "observed_at": item["observed_at"],
                       "source_input_sha256": item["source_input_sha256"],
                       "predicted_labels": answers})
    return {"schema": SCHEMA + ".class-predictions", "synthetic_data": True,
            "arms": list(ARMS), "geometry_pred_sha256": sha(canon(geometry)),
            "class_names": list(CLASSES), "rows": result,
            "future_labels_seen": False, "production_accepted": False,
            "authority": "DENY_ALL"}


def fit_predict(source: Path, output: Path, dino: Path, granite: Path,
                granite_profile: Path):
    """Model checkpoint bytes must be physically installed, fully hashed by owners."""
    from e2_real_vision_features import run as vision_run
    from e2_real_vision_bridge_ingress import produce as vision_ingress
    from multimodal_alignment_contract import sha as align_sha, canonical
    from multimodal_alignment import train, predict
    from multimodal_real_encoder import run_offline
    manifest = get_json(source.parent / "source-manifest.json")
    train_cases, future_cases = _verify_split(source, manifest)
    # Never opens any future target path. The workflow gives this job only source artifact.
    output.mkdir(parents=True, exist_ok=False)
    def physical(phase):
        snap = dino
        image_src = source / ("train_images.jsonl" if phase == "train" else "future_images.jsonl")
        return vision_run(snap, source / "images", image_src, manifest["file_sha256s"][image_src.name], phase,
                          sha((snap / "config.json").read_bytes()),
                          sha((snap / "preprocessor_config.json").read_bytes()),
                          output / ("vision_" + phase))
    train_receipt = physical("train")
    future_receipt = physical("future")
    assert train_receipt["actual_model_forwards"] == 16 and future_receipt["actual_model_forwards"] == 8
    with (output / "vision_train" / "features.jsonl").open("rb") as f:
        train_v = f.read()
    with (output / "vision_future" / "features.jsonl").open("rb") as f:
        future_v = f.read()
    paired = vision_ingress(train_v, train_receipt, phase="train", anchors=(source / "train_anchors.jsonl").read_bytes())
    futures = vision_ingress(future_v, future_receipt, phase="future")
    train_in = output / "train_bridge.jsonl"
    future_in = output / "future_bridge.jsonl"
    train_in_sha = put(train_in, b"".join(canonical(x) for x in paired))
    future_in_sha = put(future_in, b"".join(canonical(x) for x in futures))
    profile_sha = sha(granite_profile.read_bytes())
    real_receipt = run_offline(granite_profile, profile_sha, granite,
                               train_in, train_in_sha, output / "granite_train", "train")
    if (real_receipt.get("model_checkpoint_locally_verified") is not True or
        real_receipt.get("model_publisher_authenticated") is not False or
        real_receipt.get("physical_forwards", 0) < 1):
        raise GateError("real pinned Granite model execution not evidenced")
    from multimodal_alignment_contract import load_pinned_jsonl, write_new
    data, inputsha = load_pinned_jsonl(output / "granite_train" / "encoded.jsonl", real_receipt["encoded_sha256"])
    fitted = train(data, inputsha)
    fitted_sha = write_new(output / "bridge_fit.json", fitted)
    future_rows, fsha = load_pinned_jsonl(future_in, future_in_sha)
    predictions = predict(fitted, future_rows, fitted_sha, fsha)
    prediction_sha = write_new(output / "sealed_geometry_predictions.json", predictions)
    classes = rows(source / "train_class.jsonl")
    label_pred = _class_predictions(predictions, data, classes)
    label_sha = write_new(output / "sealed_class_predictions.json", label_pred)
    summary = {"schema": SCHEMA + ".producer-receipt", "synthetic_data": True,
               "original_vision_source_sha256": manifest["file_sha256s"]["train_images.jsonl"],
               "original_future_vision_source_sha256": manifest["file_sha256s"]["future_images.jsonl"],
               "dino_model_revision": train_receipt["encoder_revision"],
               "dino_model_weights_sha256": train_receipt["snapshot_file_sha256s"]["model.safetensors"],
               "dino_train_forwards": train_receipt["actual_model_forwards"],
               "dino_future_forwards": future_receipt["actual_model_forwards"],
               "granite_model_revision": real_receipt["model_revision"],
               "granite_model_profile_sha256": profile_sha,
               "granite_train_forwards": real_receipt["physical_forwards"],
               "aligned_train_sha256": real_receipt["encoded_sha256"],
               "bridge_fit_sha256": fitted_sha,
               "sealed_geometry_predictions_sha256": prediction_sha,
               "sealed_class_predictions_sha256": label_sha,
               "future_labels_seen": False, "model_publisher_independently_authenticated": False,
               "stem_selected": False, "production_accepted": False, "authority": "DENY_ALL"}
    put(output / "producer_receipt.json", canon(summary))
    return summary


def target_digest(withheld_manifest: dict, source_manifest_bytes: bytes, filename: str) -> str:
    """Target SHA-256 exists only in evaluator-owned artifact, never model inputs."""
    if (type(withheld_manifest) is not dict or
        set(withheld_manifest) != {"schema", "synthetic_data", "source_manifest_sha256",
                                   "file_sha256s", "production_accepted", "authority"} or
        withheld_manifest["schema"] != SCHEMA + ".withheld-target-plan" or
        withheld_manifest["synthetic_data"] is not True or
        withheld_manifest["production_accepted"] is not False or
        withheld_manifest["authority"] != "DENY_ALL" or
        withheld_manifest["source_manifest_sha256"] != sha(source_manifest_bytes) or
        type(withheld_manifest["file_sha256s"]) is not dict or
        set(withheld_manifest["file_sha256s"]) != TARGET_FILES or filename not in TARGET_FILES):
        raise GateError("unbound or exposed withheld target manifest")
    digest = withheld_manifest["file_sha256s"][filename]
    if type(digest) is not str or len(digest) != 64 or any(x not in '0123456789abcdef' for x in digest):
        raise GateError("invalid withheld target digest")
    return digest


def evaluate_geometry(predicted: Path, withheld: Path, output: Path, granite: Path,
                      granite_profile: Path):
    """Independent future-label process; do not run any bridge fitting here."""
    from multimodal_real_encoder import run_offline
    from multimodal_alignment_evaluator import evaluate as eval_geometry
    from multimodal_alignment_contract import load_pinned_document, load_pinned_jsonl, write_new
    p = predicted / "sealed_geometry_predictions.json"
    prediction_sha = sha(p.read_bytes())
    receipt = get_json(predicted / "producer_receipt.json")
    if prediction_sha != receipt["sealed_geometry_predictions_sha256"] or receipt["future_labels_seen"] is not False:
        raise GateError("unsealed prediction data")
    source_manifest_bytes = (withheld.parent / "source-manifest.json").read_bytes()
    src = withheld / "future_caption_targets.jsonl"
    withheld_manifest = get_json(withheld / "target-manifest.json")
    tgt_sha = target_digest(withheld_manifest, source_manifest_bytes, src.name)
    if sha(src.read_bytes()) != tgt_sha:
        raise GateError("withheld future captions modified")
    output.mkdir(parents=True, exist_ok=False)
    profile_sha = sha(granite_profile.read_bytes())
    future_rcpt = run_offline(granite_profile, profile_sha, granite,
                              src, tgt_sha, output / "granite_future_targets", "future_targets")
    if future_rcpt.get("model_checkpoint_locally_verified") is not True or future_rcpt.get("physical_forwards", 0) < 1:
        raise GateError("future evaluator did not physically encode original Granite targets")
    geometry = load_pinned_document(p, prediction_sha)
    target_rows, future_sha = load_pinned_jsonl(output / "granite_future_targets" / "encoded.jsonl", future_rcpt["encoded_sha256"])
    result = eval_geometry(geometry, target_rows, prediction_sha, future_sha)
    result["physical_future_granite_forward_batches"] = future_rcpt["physical_forwards"]
    result["production_accepted"] = False
    write_new(output / "geometry_independent_readout.json", result)
    # Pure-stdlib class scorer is a different process, invoked separately from CLI.
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="cmd", required=True)
    p=sub.add_parser("prepare"); p.add_argument("--out", type=Path, required=True)
    p=sub.add_parser("fit-predict")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--dino", type=Path, required=True)
    p.add_argument("--granite", type=Path, required=True)
    p.add_argument("--granite-profile", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p=sub.add_parser("evaluate-geometry")
    p.add_argument("--predicted", type=Path, required=True)
    p.add_argument("--withheld", type=Path, required=True)
    p.add_argument("--granite", type=Path, required=True)
    p.add_argument("--granite-profile", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args=parser.parse_args()
    if args.cmd=="prepare":
        print(json.dumps(prepare(args.out), sort_keys=True))
    elif args.cmd=="fit-predict":
        print(json.dumps(fit_predict(args.source, args.out, args.dino,
                                     args.granite, args.granite_profile), sort_keys=True))
    else:
        print(json.dumps(evaluate_geometry(args.predicted, args.withheld,
                                           args.out, args.granite, args.granite_profile), sort_keys=True))

if __name__=="__main__":
    main()
