"""Descriptive posthoc summaries; no source label or primary selection access."""

from collections import Counter
from pathlib import Path

import numpy as np

from run_loss2_stop_diagnostic import file_hash, read, require, write


def summarize(directory):
    root = Path(directory)
    report, census = read(root/"report.json"), read(root/"case-table.json")
    require(file_hash(root/"case-table.json") == report["case_table_sha256"] and len(census) == 288, "complete diagnostic census")
    records, errors, shared, cross, failures = [], [], [], {}, []
    action_error = state_error = 0.
    for row in census:
        if row["diagnostic_status"] != "executed":
            continue
        case = root/f"config{row['configuration_index']:02d}"/row["fit_id"]
        record = read(case/"diagnostic.json")
        records.append(record)
        original = row["original_status"]
        group = cross.setdefault(original, {"origins": 0, "full_safe": 0, "field_safe": 0, "hold_safe": 0})
        group["origins"] += 1
        for short, name in (("full", "full"), ("field", "future_field"), ("hold", "parameter_hold")):
            group[short+"_safe"] += int(record["branches"][name]["certified"])
        if not record["full_actual_safe_witness"]:
            failures.append({"configuration_index": row["configuration_index"], "fit_id": row["fit_id"],
                "original_status": original, "branches": row["branches"]})
        predictions = [item for item in record["terminal_prediction_errors"]
            if item["target"] == "full" and item["status"] == "computed"]
        if predictions:
            require(len(predictions) == 3, "all three available forecasts of each actual Full witness")
            common = len({(item["nominal_actions_sha256"], item["reference_states_sha256"]) for item in predictions}) == 1
            for item in predictions:
                delta = np.asarray(item["predicted_terminal_panels"])-np.asarray(item["actual_terminal_panels"])
                require(np.array_equal(delta, item["error"]) and float(np.sqrt(np.mean(delta**2))) == item["rmse"], "forecast arithmetic")
                errors.append((item["predictor"], delta))
                if common:
                    shared.append((item["predictor"], delta))
        if record["branches"]["full"]["certified"] and record["branches"]["future_field"]["certified"]:
            with np.load(case/"arrays.npz", allow_pickle=False) as arrays:
                action_error = max(action_error, float(np.max(np.abs(arrays["full_actions"]-arrays["future_field_actions"]))))
                state_error = max(state_error, float(np.max(np.abs(arrays["full_states"]-arrays["future_field_states"]))))
    def metrics(rows):
        result = {}
        for name in ("full", "loss2", "future_field"):
            values = np.asarray([error for predictor, error in rows if predictor == name]).reshape(-1, 8)
            result[name] = {"origins": len(values), "pooled_q8_rmse": float(np.sqrt(np.mean(values**2))) if len(values) else None,
                "current4_rmse": float(np.sqrt(np.mean(values[:, :4]**2))) if len(values) else None,
                "old4_rmse": float(np.sqrt(np.mean(values[:, 4:]**2))) if len(values) else None,
                "mean_per_origin_q8_rmse": float(np.mean(np.sqrt(np.mean(values**2, axis=1)))) if len(values) else None}
        return result
    result = {"schema": "hepta.loss2-stop-mechanism-summary.v7", "report_sha256": file_hash(root/"report.json"),
        "source_sha256": file_hash(__file__), "all_stopped_origins": len(records), "all_branch_records": 4*len(records),
        "safe_witnesses_by_original_stop": cross, "origins_without_a_full_safe_witness": failures,
        "forecasts_of_exact_executed_full_actions_all_last_nominals": metrics(errors),
        "forecasts_restricted_to_exact_common_nominal_and_reference": metrics(shared),
        "full_field_actual_action_max_abs": action_error, "full_field_actual_full_state_max_abs": state_error,
        "hold_failures": dict(Counter(record["branches"]["parameter_hold"]["status"] for record in records)),
        "scope": "conditional descriptive census of stopped Loss2 origins; all-method common-reference subset is reported separately; no independent sample or utility inference",
        "primary_selection_changed": False, "selection_labels_used": False, "scientific_acceptance": False}
    write(root/"mechanism-summary.json", result)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    print(summarize(**vars(parser.parse_args())))
