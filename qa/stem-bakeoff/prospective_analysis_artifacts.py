"""Authenticate fixed prospective prediction artifacts before joining any outcomes."""

import io
import json
from pathlib import Path
import zipfile

import numpy as np

from cell_action_inference import _input_digest
from cell_action_prepare import DEFAULT_PROTOCOL, code_hashes as preparation_code_hashes
from prospective_analysis_plan import ARMS, BUDGETS, CONTROLS, SEEDS, sha, source_digest


def bounded_array(raw, shape, kind):
    """Validate the NPY header before any array allocation, including compressed members."""
    stream = io.BytesIO(raw)
    version = np.lib.format.read_magic(stream)
    if version not in ((1, 0), (2, 0)):
        raise ValueError("unsupported numeric NPY version")
    reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
    declared, fortran, dtype = reader(stream)
    if (declared != tuple(shape) or dtype.kind not in kind or dtype.hasobject or dtype.itemsize > 8
            or stream.tell()+int(np.prod(shape))*dtype.itemsize != len(raw)):
        raise ValueError("numeric array shape/type/byte budget differs before allocation")
    return np.frombuffer(raw, dtype, offset=stream.tell()).reshape(shape, order="F" if fortran else "C")


class CapturedArtifacts:
    """Keep initial independent pins; a later read can never adopt changed bytes."""
    def __init__(self):
        self.pins, self.roots = {}, {}

    def read(self, path, expected=None):
        path = Path(path).absolute()
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 128*1024**2:
            raise ValueError("bounded ordinary analysis artifact required")
        raw = path.read_bytes()
        record = {"sha256": sha(raw), "bytes": len(raw)}
        if len(raw) > 128*1024**2 or (expected is not None and record["sha256"] != expected):
            raise ValueError("independent artifact pin differs")
        if self.pins.setdefault(str(path), record) != record:
            raise ValueError("artifact changed after initial capture")
        return raw

    def document(self, path, expected=None):
        return json.loads(self.read(path, expected))

    def tree(self, root, seal_sha256):
        root = Path(root).absolute()
        if root.is_symlink() or not root.is_dir():
            raise ValueError("ordinary artifact root required")
        seal = self.document(root/"seal.json", seal_sha256)
        names = set(seal["files"]) | {"seal.json"}
        if (not 1 <= len(names) <= 16384 or any(type(v["bytes"]) is not int or v["bytes"] < 0 for v in seal["files"].values())
                or sum(v["bytes"] for v in seal["files"].values()) > 512*1024**2):
            raise ValueError("bounded sealed artifact inventory required")
        for name, record in seal["files"].items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
                raise ValueError("sealed path must remain inside its artifact root")
            raw = self.read(root/relative, record["sha256"])
            if len(raw) != record["bytes"]:
                raise ValueError("sealed artifact size differs")
        self.roots.setdefault(str(root), names)
        self._members(root, names)
        return seal

    @staticmethod
    def _members(root, names):
        paths = list(Path(root).rglob("*"))
        if any(p.is_symlink() for p in paths) or {p.relative_to(root).as_posix() for p in paths if p.is_file()} != names:
            raise ValueError("extra, missing or symbolic-link artifact")

    def verify(self):
        for root, names in self.roots.items():
            self._members(root, names)
        for path, record in list(self.pins.items()):
            if len(self.read(path, record["sha256"])) != record["bytes"]:
                raise ValueError("captured artifact size changed")

    def prediction(self, path, expected, count, *, fresh=False):
        raw = self.read(path, expected)
        required = {"logits", "probabilities"} | (set() if fresh else {"eligible"})
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 128*1024**2:
                raise ValueError("expanded prediction archive exceeds bound")
            if set(archive.namelist()) != {name+".npy" for name in required} or len(archive.namelist()) != len(required):
                raise ValueError("prediction archive fields differ")
            arrays = {name: bounded_array(archive.read(name+".npy"), (count,) if name == "eligible" else (count, 2),
                "b" if name == "eligible" else "f") for name in required}
        for key in ("logits", "probabilities"):
            value = arrays[key]
            if value.shape != (count, 2) or value.dtype.kind != "f" or not np.isfinite(value).all():
                raise ValueError("finite ordered binary predictions required")
        p = arrays["probabilities"]
        if np.any((p < 0) | (p > 1)) or not np.allclose(p.sum(axis=1), 1, atol=1e-12, rtol=0):
            raise ValueError("normalized binary probabilities required")
        if not fresh and (arrays["eligible"].dtype != np.bool_ or arrays["eligible"].shape != (count,)):
            raise ValueError("explicit ordered boolean eligibility required")
        return arrays


def validate_dataset(data, plan):
    if (data.get("input_dataset_sha256") != plan["input_dataset_sha256"]
            or data.get("governing_protocol_sha256") != plan["governing_protocol_sha256"]
            or data.get("all_proposed_actions_retained") is not True
            or data.get("post_outcome_candidate_selection") is not False
            or data["selected_tasks"] != [plan["task_id"]] or len(data["rows"]) != len(plan["rows"])):
        raise ValueError("final outcomes must retain the complete predeclared input condition")
    rows = {}
    for row, source in zip(data["rows"], plan["rows"], strict=True):
        labels = row["labels"]
        if (source_digest(row) != source["source_digest"] or row["source_id"] != source["source_id"]
                or set(labels) != {plan["task_id"]}
                or any(v is not None and (type(v) is not int or v not in (0, 1)) for v in labels.values())):
            raise ValueError("source order/content or explicit binary-or-unknown target differs")
        rows[row["source_id"]] = row
    actual = {g["group_id"]: g for g in data["proposal_registry"]}
    if len(actual) != len(data["proposal_registry"]) or set(actual) != {g["group_id"] for g in plan["proposal_shape"]}:
        raise ValueError("complete unique proposal groups required")
    for original in plan["proposal_shape"]:
        group = actual[original["group_id"]]
        if (any(group[k] != original[k] for k in ("repo", "split"))
                or len(group["actions"]) != len(original["actions"])):
            raise ValueError("proposal group role or action denominator changed")
        for action, before in zip(group["actions"], original["actions"], strict=True):
            label = action["label"]
            if (any(action.get(key) != value for key, value in before.items())
                    or (label is not None and (type(label) is not int or label not in (0, 1)))
                    or (action["source_id"] is not None and rows[action["source_id"]]["labels"][plan["task_id"]] != label)):
                raise ValueError("proposal/source target binding or pre-observation action changed")
    return rows, [actual[group] for group in plan["expected_holdout_group_ids"]]


def verify_alias_lineage(captured, condition, planned, plan, dataset_sha256):
    """Tie the entire train/tune/calibration/query tensor to its pre-label origin."""
    root = Path(condition["feature_directory"])
    alias = captured.document(root/"report.json", condition["feature_report_sha256"])
    original = Path(planned["feature_report_path"])
    parent = captured.document(original, planned["feature_report_sha256"])
    captured.read(original.with_name("manifest.json"), planned["feature_manifest_sha256"])
    binding = captured.document(root/"label-binding.json")
    expected = {"dataset_sha256": dataset_sha256, "feature_report_sha256": condition["feature_report_sha256"],
                "proposal_plan_sha256": plan["input_dataset_sha256"]}
    fields = ("feature_identity", "feature_shape", "feature_archive_sha256", "feature_tensor_sha256",
              "feature_availability_sha256", "source_bindings_sha256", "source_record_digests")
    if (condition["input_bindings"] != expected or alias["condition"] != condition["name"]
            or alias["feature_identity"] != planned["feature_identity"]
            or any(alias[key] != parent[key] for key in fields)
            or parent["feature_archive_sha256"] != planned["feature_archive_sha256"]
            or parent["plan"]["dataset_sha256"] != plan["input_dataset_sha256"]
            or alias["plan"]["dataset_sha256"] != dataset_sha256
            or alias["plan"]["source_ids"] != [r["source_id"] for r in plan["rows"]]
            or binding != alias["label_binding"] or binding != alias["plan"]["label_attachment"]
            or binding["parent_report_sha256"] != planned["feature_report_sha256"]
            or binding["parent_manifest_sha256"] != planned["feature_manifest_sha256"]
            or binding["parent_dataset_sha256"] != plan["input_dataset_sha256"]
            or binding["labelled_dataset_sha256"] != dataset_sha256
            or binding["permitted_row_changes"] != ["labels", "outcome_provenance"]
            or any(binding[key] is not True for key in ("numeric_payloads_byte_identical", "feature_availability_unchanged",
                                                       "all_source_versions_text_spans_order_identical"))
            or alias["encoder_forward_calls"] != 0 or alias["gradient_updates"] != 0):
        raise ValueError("label alias changed the planned whole-feature archive, proposal or source origin")
    for filename, key in (("features.npz", "feature_archive_sha256"), ("feature-availability.json", "feature_availability_sha256"),
                          ("source-bindings.json", "source_bindings_sha256")):
        captured.read(root/filename, parent[key])
    return expected


def load_condition(captured, condition, planned, rows, dataset_sha256):
    """Verify source order, all private arms/controls, and independent-process parity."""
    if condition["feature_identity"] != planned["feature_identity"]:
        raise ValueError("condition feature identity differs from pre-inference plan")
    prepared, root = Path(condition["prepared_dir"]), Path(condition["inference_dir"])
    captured.tree(prepared, condition["preparation_seal_sha256"])
    frozen = captured.document(prepared/"frozen.json", condition["preparation_report_sha256"])
    captured.tree(root, condition["inference_seal_sha256"])
    report = captured.document(root/"report.json", condition["inference_report_sha256"])
    pp, ip = frozen["plan"], report["plan"]
    source_ids = planned["holdout_source_ids"]
    public = [{key: rows[s][key] for key in ("source_id", "group_id", "text")} for s in source_ids]
    if (pp["feature_identity"] != planned["feature_identity"] or pp["width"] != planned["width"]
            or pp["code_sha256"] != preparation_code_hashes()
            or pp["input_bindings"]["dataset_sha256"] != dataset_sha256
            or pp["input_bindings"] != condition["input_bindings"]
            or pp["configuration"] != DEFAULT_PROTOCOL
            or not frozen["all_choices_frozen_before_heldout_scoring"]
            or ip["input_bindings"] != pp["input_bindings"] or ip["feature_identity"] != pp["feature_identity"]
            or ip["prepared_seal_sha256"] != condition["preparation_seal_sha256"]
            or ip["labels_or_outcomes_received"] or ip["metrics_computed"] or ip["fitting_performed"]
            or ip["prediction_role"] != "prospective_external_candidates"
            or report["source_ids"] != source_ids or report["group_ids"] != [r["group_id"] for r in public]
            or report["unavailable"] != frozen["unavailable"]):
        raise ValueError("sealed preparation or label-free prediction/source contract differs")
    x = bounded_array(captured.read(root/"features.npy"), (len(public), planned["width"]), "f")
    if (x.dtype != np.float32 or x.shape != (len(public), planned["width"])
            or sha(x.tobytes()) != planned["holdout_feature_tensor_sha256"]
            or ip["input_sha256"] != _input_digest(x, public)):
        raise ValueError("prediction features or complete public input order differ")
    prepared_runs = {(r["seed"], r["budget"]): r for r in frozen["runs"]}
    if len(prepared_runs) != len(frozen["runs"]) or len(report["runs"]) != len(prepared_runs):
        raise ValueError("duplicate or missing frozen run")
    result = {}
    for run in report["runs"]:
        key = (run["seed"], run["budget"])
        before = prepared_runs.get(key)
        if (any(type(v) is not int for v in key) or key in result or before is None
                or set(run["arms"]) != set(ARMS) or set(before["arms"]) != set(ARMS)
                or run["directory"] != f"seed-{key[0]}_n-{key[1]}"
                or any(run[k] != before[k] for k in ("directory", "selected_arm", "selection_source"))
                or run["selection_source"] != "independent_tuning_repositories_only"):
            raise ValueError("prediction arms or frozen tuning selection differ")
        directory = root/run["directory"]
        variants = {}
        for name, receipt in run["arms"].items():
            spec = before["arms"][name]
            if receipt["prediction_file"] != name+".npz" or receipt["rows"] != len(public):
                raise ValueError("prediction filename/count differs")
            values = captured.prediction(directory/receipt["prediction_file"], receipt["prediction_sha256"], len(public))
            if (receipt["eligible_rows"] != int(values["eligible"].sum()) or receipt["calibration"] != spec.get("calibration")
                    or receipt["trainable_parameters"] != spec["trainable_parameters"]):
                raise ValueError("prediction eligibility or frozen calibration differs")
            prior = spec["prior"][1] if spec["kind"] == "prior" else spec["calibration"]["prior_positive"]
            variants[name] = {"values": values, "receipt": receipt, "prior": prior}
            if spec["kind"] == "head":
                fresh = receipt["fresh_process"]
                replay = captured.prediction(directory/(name+"-fresh.npz"), fresh["output_sha256"], len(public), fresh=True)
                if (not fresh["bitwise_equal_logits_and_probabilities"] or fresh["test_labels_provided_to_child"]
                        or receipt["tensor_sha256"] != spec["predictor_sha256"]
                        or any(replay[k].dtype != values[k].dtype or replay[k].tobytes() != values[k].tobytes()
                               for k in replay) or set(receipt["controls"]) != set(CONTROLS)):
                    raise ValueError("fresh-process parity or private control set differs")
                for control, item in receipt["controls"].items():
                    filename = name+"-"+control+".npz"
                    if (item["prediction_file"] != filename or item["rows"] != len(public)
                            or item["calibration_refitted"] or item["retained_calibration_predictor_sha256"] != spec["predictor_sha256"]):
                        raise ValueError("private control was rebound or refitted")
                    changed = captured.prediction(directory/filename, item["prediction_sha256"], len(public))
                    if (item["eligible_rows"] != int(changed["eligible"].sum())
                            or changed["eligible"].tobytes() != values["eligible"].tobytes()):
                        raise ValueError("private control eligibility differs")
                    variants[name+"/"+control] = {"values": changed, "receipt": item, "prior": prior}
        variants["selected"] = variants[run["selected_arm"]]
        result[key] = {"variants": variants, "run": run}
    expected = {(seed, budget) for seed in SEEDS for budget in BUDGETS}
    unavailable = {(v["seed"], v["budget"]) for v in frozen["unavailable"] if v["budget"] in BUDGETS}
    if set(result) & unavailable or set(result) | unavailable != expected:
        raise ValueError("each requested run must be executed or explicitly unavailable")
    return {"runs": result, "report": report, "frozen": frozen, "source_ids": source_ids, "public_rows": public}
