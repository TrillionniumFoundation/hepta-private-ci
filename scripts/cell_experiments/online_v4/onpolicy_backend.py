"""Bind the new loop to unchanged authored-A admission and actual model execution."""

import copy
import importlib
from pathlib import Path

from .. import data
from ..coding_sft import write_new
from . import onpolicy_contract as contract, onpolicy_train
from .onpolicy_rollout import collect_current


class ResearchBackend:
    """Use explicit research operations after the caller binds the original helpers."""

    def __init__(self, context, artifact_root):
        self.context, self.root = context, Path(artifact_root)
        self.old = contract.legacy()
        self.execution = importlib.import_module("research_sft_execution_v1")
        self.execution.configure(self.old.helpers().directory)
        self.old.reference_admission(context["records"][:6], context, "trajectory")

    def sources(self):
        return contract.sources()

    def verify_model(self, manifest):
        return contract.verify_model(manifest, self.root)

    def collect(self, records, current, output, mode, maximum):
        if mode == "teacher":
            result = {
                "schema": "hepta.current-policy-collection.v1",
                "model_digest": data.digest(current),
                "rows": [],
                "records_digest": data.digest(records),
                "model_calls": 0,
                "student_verifier_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "reused_observation_count": 0,
                "independent_sample_increment": 0,
                "complete": True,
                "full_system_cost_complete": False,
                "collection_mode": "teacher",
                "student_called": False,
            }
            write_new(Path(output) / "COLLECTION.json", result)
            return result
        return collect_current(
            records,
            current,
            self.root,
            output,
            onpolicy_train.load_predictor,
            maximum=maximum if mode == "controlled" else 1,
            execute=mode == "controlled",
        )

    def corrections(self, records, collection, mode, round_index, output):
        contract.require(
            mode == "teacher" or len(collection["rows"]) == len(records),
            "collection coverage differs from A",
        )
        result = []
        for index, original in enumerate(records):
            row = copy.deepcopy(original)
            row["record_id"] += "/current-policy-round-" + str(round_index)
            directory = Path(output) / str(index)
            if mode == "teacher":
                receipt = self.old.recheck_reference(row, directory)
                row["protocol_reference_receipt"] = receipt
                row["verified_outcome"] = {
                    "success": True,
                    "receipt_sha256": receipt["receipt_sha256"],
                    "verifier_name": "repo_patch",
                    "verifier_version": "1",
                }
                row["derivation"] = {
                    "original_record_digest": data.digest(original),
                    "mode": "authored_teacher_only",
                    "independent_sample_increment": 0,
                }
            else:
                observed = collection["rows"][index]
                contract.require(
                    observed["task_id"] == row["task_id"]
                    and observed["model_digest"] == collection["model_digest"],
                    "observation belongs to another current policy or task",
                )
                row = self.execution.corrected(row, observed, mode, directory)
            row["onpolicy_derivation"] = {
                "original_record_digest": data.digest(original),
                "round_index": round_index,
                "current_model_digest": collection["model_digest"],
                "collection_digest": data.digest(collection),
                "retention": "latest_round_only",
                "target_origin": "verified authored A reference",
                "external_teacher": False,
            }
            data.validate_record(row)
            result.append(row)
        return result

    def make_plan(self, records, current, operation_id, round_index, mode):
        return contract.make_plan(
            records,
            current,
            self.root,
            self.context,
            operation_id=operation_id,
            round_index=round_index,
            mode=mode,
        )

    def fit(self, records, current, plan, output):
        return onpolicy_train.train(
            records, current, self.root, plan, output, self.context
        )

    def evaluate(self, records, current, output, maximum):
        return collect_current(
            records,
            current,
            self.root,
            output,
            onpolicy_train.load_predictor,
            maximum=maximum,
            execute=True,
        )
