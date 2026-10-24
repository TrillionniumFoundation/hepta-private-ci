"""Prepare private, integrity-pinned research owner inputs from one retained run.

No Encoder execution, Head forward, training, calibration or authority installation
occurs here. Owner pins are returned separately for a trusted host to install;
they are not source authentication or a revocation oracle. Never publish outputs.
"""

import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

import numpy as np

SOURCE_COMMIT = "5fbb4474d851d8592224b9ecb883d12500cc1412"
ZIP_SHA = "182b49d1ed8f4b29716f6bfb9926de79dedf34b8277a18ea3492cbab6dcf516e"
REPORT_SHA = "200052b3a196a42b74923041d66a257228091d6c6b21a79bb79eb5484222481b"
CASES = ("paired", "missing_text", "missing_image", "shuffled_image", "mixed_presence")
WIDTH, MAX_ROWS = 3073, 4096
HEADER_BYTES, INVENTORY_BYTES, REQUEST_BYTES = 65536, 4 * 1024**2, 32 * 1024**2
ROW_BYTES = WIDTH * 4
BINDING_FIELDS = {"case_id", "row_index", "row_id", "pair_block_id", "image_id",
                  "caption_id", "source_caption_image_id", "source_record_digest",
                  "text_provenance_sha256", "image_provenance_sha256",
                  "present_mask", "features_sha256"}
DIGEST_FIELDS = {"row_id", "pair_block_id", "source_record_digest",
                 "text_provenance_sha256", "image_provenance_sha256", "features_sha256"}
PRODUCER_SCHEME = "hepta.research-task-head-fixture-producer.v1"
SOURCE_PINS = {
    "cell_head_training.py": "90bc397602a6c59177ece45f818f33718960fb4864dcb33a2c89e2b2e1a06f4f",
    "export_native_task_head_v1.py": "d81a10db59f3957063a8cad499dc858bdc517e77b495636abdccbca9790b4bea",
    "feature_bundle.py": "0a40f17c0383d8289a9f66da871c81347ac2896f60d8bdacedcfbba503899fea",
    "multimodal_bridge.py": "10f83d200bd77aca8fa5f9aa4b3a5ba7c2c387b08b65847bc800227b91b82651",
    "multimodal_cohorts.py": "9c1d17ffbacb2d44c1b059160769a19a367fc743c4f9e216837d34f3a0b65791",
    "multimodal_features.py": "fdf74f74b8308a156284ba19221a48d56cce43556349f48c1a89a46b28ee6a55",
    "native_latent.py": "6d8db8a5911d4104d93b7e2084d8c2653fadb3191685b9cad8f34db2ab5fbc29",
    "prepare_news_cohorts.py": "33fa46322d4e9ee341b1f5ea80f37b79713a7f9420f14df9204766f38b6b45b1",
    "real_encoder.py": "6728cb9b9ecc4a3280bb8186d920ce174138ac63f7a5b9a362c2b17040f7f638",
    "real_encoder_candidates.json": "b3ca0936519a2c5f0bd6fcfe997f8e61c953db37aaa2cdc43b641ccdce956cd6",
    "real_head_fanout.py": "ceac14a698b944f3cfb931f9d0d19d6b3bc7b915140c33c3798906d3c88390df",
    "real_model_bakeoff.py": "44aac7c0429e9ab7740648d5baebf6ee6134f18d2ef79420dfef0771d4064e3a",
    "research_presence_guard.py": "8e2efae52b02fce586405a752a45d0c108c2a663b1685088bb0d4571d3ed7c0f",
    "teacher_forward.py": "ca9f1f5a1b91188905522cc87ef073b5a23cebb56eda867fc40a7d55f235a0c6",
    "teacher_media_seal.py": "6ac9b19527df6722a1061a37a8672b1e39e4b78e4e463309021d75ac4feed8cc",
    "teacher_snapshot.py": "51fe50c86b107bf5deb85145d22d49be0a622bc0204c219c3bd45bcae86977a1",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def strict_json(raw, limit):
    require(isinstance(raw, bytes) and 0 < len(raw) <= limit, "JSON byte bound")
    return json.loads(raw, object_pairs_hook=_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) and value != "0" * 64


def validate_inventory(raw):
    inventory = strict_json(raw, INVENTORY_BYTES)
    require(type(inventory) is dict and set(inventory) == {"schema", "rows"}
            and inventory["schema"] == "hepta.research-task-head-row-inventory.v1", "inventory schema")
    rows = inventory["rows"]
    require(type(rows) is list and 0 < len(rows) <= MAX_ROWS, "inventory row bound")
    seen = set()
    seen_sources = set()
    previous = None
    for row in rows:
        require(type(row) is dict and set(row) == BINDING_FIELDS, "row binding fields")
        require(row["case_id"] in CASES and type(row["row_index"]) is int
                and 0 <= row["row_index"] < MAX_ROWS, "case or row index")
        require(all(_digest(row[key]) for key in DIGEST_FIELDS), "row digest")
        require(all(type(row[key]) is int and 0 < row[key] <= 2**64 - 1
                    for key in ("image_id", "caption_id", "source_caption_image_id")), "endpoint integer")
        require(type(row["present_mask"]) is int and 0 <= row["present_mask"] <= 31, "presence mask")
        key = (row["case_id"], row["row_index"])
        require(key not in seen, "duplicate row binding")
        source_key = (row["case_id"], row["row_id"])
        require(source_key not in seen_sources, "duplicate case source row")
        seen_sources.add(source_key)
        order = (CASES.index(row["case_id"]), row["row_index"])
        require(previous is None or order > previous, "inventory row order")
        previous = order
        seen.add(key)
    return inventory


def _bounded_file(path, limit):
    require(not path.is_symlink() and path.is_file(), "regular input file required")
    require(path.stat().st_size <= limit, "file byte bound")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "file grew beyond byte bound")
    return raw


def _helper_source_path(name):
    module = "real_encoder" if name.endswith(".json") else name[:-3]
    spec = importlib.util.find_spec(module)
    require(spec is not None and spec.origin is not None, "helper source unavailable")
    return Path(spec.origin).with_name(name)


def _producer_identity(report):
    sources = {Path(__file__).name: sha(_bounded_file(Path(__file__), 128 * 1024))}
    retained = report["plan"]["code_file_sha256"]
    for name, expected in SOURCE_PINS.items():
        actual = sha(_bounded_file(_helper_source_path(name), 128 * 1024))
        require(actual == expected, "fixture helper source drift: " + name)
        require(name not in retained or retained[name] == actual, "retained plan code pin differs: " + name)
        sources[name] = actual
    return sha(PRODUCER_SCHEME.encode() + b"\0" + canonical(sources)), sources


def _source_archive(path):
    raw = _bounded_file(path, 8 * 1024**2)
    require(sha(raw) == ZIP_SHA, "fixed source ZIP pin mismatch")
    archive = zipfile.ZipFile(io.BytesIO(raw))
    infos = archive.infolist()
    names = [entry.filename for entry in infos]
    require(len(names) == len(set(names)) and len(names) == 110
            and sum(entry.file_size for entry in infos) <= 24 * 1024**2, "source ZIP inventory bound")
    for entry in infos:
        p = PurePosixPath(entry.filename)
        require(not p.is_absolute() and ".." not in p.parts and "\\" not in entry.filename
                and not stat.S_ISLNK(entry.external_attr >> 16) and not entry.flag_bits & 1
                and entry.file_size <= 8 * 1024**2, "unsafe source ZIP entry")
    report_raw = archive.read("results/report.json")
    require(sha(report_raw) == REPORT_SHA, "fixed source report pin mismatch")
    report = strict_json(report_raw, 128 * 1024)
    index = report["artifact_sha256"]
    require(len(index) == 77 and {"results/" + name for name in index} | {"results/report.json"}
            == {name for name in names if name.startswith("results/")}, "report artifact inventory")
    for name, digest in index.items():
        require(sha(archive.read("results/" + name)) == digest, "indexed artifact drift")
    require(archive.read("source-sha.txt").decode().strip() == SOURCE_COMMIT, "source commit mismatch")
    require(report["authority"] == "DENY_ALL" and report["production_activation_allowed"] is False,
            "source authority mismatch")
    return archive, report


def _write(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)


def _retained_rows(archive, report):
    raw = archive.read("cohorts/manifest.json")
    require(sha(raw) == report["data_manifest_sha256"], "cohort manifest pin")
    cohort = strict_json(raw, 1024**2)
    raw = archive.read("cohorts/test.jsonl")
    require(sha(raw) == cohort["splits"]["test"]["jsonl_sha256"], "test rows pin")
    rows = [strict_json(line, 8192) for line in raw.splitlines()]
    require(len(rows) == 256 and len({r["row_id"] for r in rows}) == 256
            and all(r["split"] == "test" and type(r["label"]) is int and r["label"] in (0, 1)
                    for r in rows) and sum(r["label"] for r in rows) == 128, "fixed test row inventory")
    return rows


def _feature_rows(rows, bank, features):
    from multimodal_features import pair_features
    bundles = {case: pair_features(rows, bank, features, arm="text_image", intervention=case)
               for case in CASES[:-1]}
    views = {case: bundle.snapshot() for case, bundle in bundles.items()}
    index = {image: i for i, image in enumerate(bank["image_ids"])}
    blocks = {}
    for row in rows:
        blocks.setdefault(row["pair_block_id"], set()).add(row["image_id"])
    require(all(len(value) == 2 for value in blocks.values()), "two-image pair blocks required")
    partner = {}
    for value in blocks.values():
        a, b = sorted(value)
        partner.update({a: b, b: a})
    for case in CASES:
        for i, row in enumerate(rows):
            variant = CASES[i % 3] if case == "mixed_presence" else case
            bundle = bundles[variant]
            vector = views[variant]["global_features"][i].numpy().astype("<f4", copy=False)
            require(vector.shape == (WIDTH,) and np.isfinite(vector).all(), "derived feature shape")
            raw = vector.tobytes(order="C")
            missing = views[variant]["missing_mask"][i].tolist()
            image = partner[row["image_id"]] if variant == "shuffled_image" else row["image_id"]
            binding = {"case_id": case, "row_index": i, "row_id": row["row_id"],
                       "pair_block_id": row["pair_block_id"], "image_id": image,
                       "caption_id": row["caption_id"], "source_caption_image_id": row["source_caption_image_id"],
                       "source_record_digest": bundle.source_record_digests[i],
                       "text_provenance_sha256": bank["provenance"]["text"][index[row["source_caption_image_id"]]],
                       "image_provenance_sha256": bank["provenance"]["image"][index[image]],
                       "present_mask": sum(int(not absent) << bit for bit, absent in enumerate(missing)),
                       "features_sha256": sha(raw)}
            yield binding, raw, bundle.identity
    for bundle in bundles.values():
        bundle.verify_integrity()


def prepare_fixture(artifact, output):
    artifact, output = Path(artifact).absolute(), Path(output).absolute()
    require(not output.exists() and not output.is_symlink() and output.parent.is_dir(), "new output directory required")
    archive, report = _source_archive(artifact)
    producer_sha, producer_sources = _producer_identity(report)
    from export_native_task_head_v1 import export_native_head
    from multimodal_features import load_bank
    with archive, tempfile.TemporaryDirectory(prefix="hepta-shadow-owner-") as temporary:
        temporary = Path(temporary)
        bank_dir = temporary / "bank"
        bank_dir.mkdir()
        for name in ("manifest.json", "plan.json", "features.npz", "text-receipts.json", "image-receipts.json"):
            _write(bank_dir / name, archive.read("bank/" + name))
        bank, features = load_bank(bank_dir, expected_manifest_sha256=report["bank_manifest_sha256"],
                                   expected_data_sha256=report["data_manifest_sha256"])
        rows = _retained_rows(archive, report)
        output.mkdir(mode=0o700)
        bindings, identity = [], None
        with (output / "features.f32le").open("xb") as stream:
            for binding, raw, identity in _feature_rows(rows, bank, features):
                bindings.append(binding)
                require(len(bindings) <= MAX_ROWS, "derived inventory row overflow")
                stream.write(raw)
        inventory = canonical({"schema": "hepta.research-task-head-row-inventory.v1", "rows": bindings})
        validate_inventory(inventory)
        _write(output / "inventory.json", inventory)
        pins = {"schema": "hepta.research-task-head-host-pins.v1", "owner_manifests": {}}
        for mode in ("gated", "linear"):
            source = temporary / mode
            source.mkdir()
            retained = report["head_artifacts"]["text_image-" + mode]
            for name in ("manifest.json", "weights.npz"):
                _write(source / name, archive.read("results/" + retained["directory"] + "/" + name))
            native = output / (mode + "-native")
            exported = export_native_head(source, expected_manifest_sha256=retained["manifest_sha256"],
                                          expected_identity=identity, output=native)
            native_header = strict_json((native / "manifest.json").read_bytes(), HEADER_BYTES)
            header = {"schema": "hepta.research-task-head-owner.v1", "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
                      "production_activation_allowed": False, "task_admission_allowed": False, "action_execution_allowed": False,
                      "source_commit": SOURCE_COMMIT, "source_report_sha256": REPORT_SHA,
                      "source_plan_sha256": report["plan_sha256"], "cohort_manifest_sha256": report["data_manifest_sha256"],
                      "bank_manifest_sha256": report["bank_manifest_sha256"], "feature_payload_sha256": bank["features_sha256"],
                      "producer_code_sha256": producer_sha, "source_head_manifest_sha256": retained["manifest_sha256"],
                      "source_head_weights_sha256": retained["weights_file_sha256"],
                      "native_head_manifest_sha256": exported["manifest_sha256"], "native_head_weights_sha256": exported["weights_sha256"],
                      "feature_identity": asdict(identity), "inventory_sha256": sha(inventory), "inventory_rows": len(bindings)}
            for key in ("feature_layout", "width", "required_present_mask", "temperature", "confidence_threshold", "state_contract", "numeric_profile"):
                header[key] = native_header[key]
            raw = canonical(header)
            require(len(raw) <= HEADER_BYTES, "owner header byte overflow")
            _write(output / (mode + "-owner.json"), raw)
            pins["owner_manifests"][mode] = {"owner_manifest_sha256": sha(raw), "native_manifest_sha256": exported["manifest_sha256"]}
        _write(output / "host-pins.json", canonical(pins))
        receipt = {"schema": "hepta.research-task-head-fixture-receipt.v1", "source_zip_sha256": ZIP_SHA,
                   "source_report_sha256": REPORT_SHA, "source_commit": SOURCE_COMMIT, "inventory_rows": len(bindings),
                   "producer_identity_scheme": PRODUCER_SCHEME, "producer_code_sha256": producer_sha,
                   "producer_source_sha256": producer_sources,
                   "new_training_or_calibration": False, "encoder_calls": 0, "head_forward_calls": 0,
                   "integrity_root_is_independent_authentication": False, "authority": "DENY_ALL",
                   "production_activation_allowed": False, "labels_in_owner_inputs": False,
                   "retained_file_sha256": {str(p.relative_to(output)): sha(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()}}
    require(sha(_bounded_file(artifact, 8 * 1024**2)) == ZIP_SHA
            and _producer_identity(report) == (producer_sha, producer_sources), "source ZIP or fixture producer changed")
    _write(output / "fixture-receipt.json", canonical(receipt))
    return receipt


def request_for_case(directory, mode, case, expected_owner_manifest_sha256):
    """Assemble one bounded request; the expected pin is supplied outside it."""
    require(mode in ("gated", "linear") and case in CASES and _digest(expected_owner_manifest_sha256), "request selection")
    root = Path(directory)
    raw = _bounded_file(root / (mode + "-owner.json"), HEADER_BYTES)
    require(sha(raw) == expected_owner_manifest_sha256, "owner pin mismatch")
    header = strict_json(raw, HEADER_BYTES)
    raw = _bounded_file(root / "inventory.json", INVENTORY_BYTES)
    require(sha(raw) == header["inventory_sha256"], "inventory pin mismatch")
    inventory = validate_inventory(raw)["rows"]
    require(type(header["inventory_rows"]) is int and len(inventory) == header["inventory_rows"], "inventory count mismatch")
    payload = _bounded_file(root / "features.f32le", MAX_ROWS * ROW_BYTES)
    require(len(payload) == len(inventory) * ROW_BYTES, "feature payload exact length")
    selected = []
    for offset, binding in enumerate(inventory):
        raw = payload[offset * ROW_BYTES:(offset + 1) * ROW_BYTES]
        require(sha(raw) == binding["features_sha256"], "feature row drift")
        values = np.frombuffer(raw, dtype="<f4")
        require(np.isfinite(values).all(), "nonfinite feature row")
        if binding["case_id"] == case:
            selected.append({"binding": binding, "features": values.tolist()})
    require(0 < len(selected) <= 512, "request row bound")
    request = canonical({"owner_manifest_sha256": expected_owner_manifest_sha256,
                         "feature_identity": header["feature_identity"], "rows": selected})
    require(len(request) <= REQUEST_BYTES, "request byte bound")
    return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("prepare")
    build.add_argument("--artifact", required=True)
    build.add_argument("--output", required=True)
    request = sub.add_parser("request")
    request.add_argument("--directory", required=True)
    request.add_argument("--mode", choices=("gated", "linear"), required=True)
    request.add_argument("--case", choices=CASES, required=True)
    request.add_argument("--expected-owner-manifest", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare_fixture(args.artifact, args.output), sort_keys=True))
    else:
        import sys
        sys.stdout.buffer.write(request_for_case(args.directory, args.mode, args.case, args.expected_owner_manifest))


if __name__ == "__main__":
    main()
