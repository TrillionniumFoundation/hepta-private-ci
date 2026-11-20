"""Charged A-only cold-versus-pool calibration before any upstream task call."""

import time

from .. import data, matched_info_sft_v4 as matched, repo_execution
from ..coding_sft import file_hash, write_new
from .circuit_contract import visible_request
from .matched_pool_v4 import MODELS
from .onpolicy_contract import require
from .shared_pool_v4 import _release_view

INPUTS_SHA256 = "691945696e7dad9ee0f3023617edf5ca0f787850c16f2623c08d14bc6cfbeaf3"


def calibrate_cold(manifests, root, training_source, run):
    """Use the first frozen A record, retaining two real cold-load generations."""
    started = time.perf_counter()
    original = root / "research-sft-02/INPUTS.json"
    require(
        file_hash(original) == INPUTS_SHA256, "original calibration A source differs"
    )
    context = data._parse(original.read_bytes())
    record = context["records"][0]
    require(
        record["split"] == "train" and record["authorization"]["training_allowed"],
        "calibration requires authorized A",
    )
    request = visible_request(record)
    repo_execution.load_catalog("open")
    directory = run / "A_SETUP_CALIBRATION"
    directory.mkdir(exist_ok=False)
    write_new(
        directory / "INTENT.json",
        {
            "schema": "hepta.matched-pool-calibration.v1",
            "rule": "first existing A training record; both preselected F/T cold and pool outputs must agree exactly",
            "record_digest": data.digest(record),
            "request": request,
            "planned_model_calls": 4,
            "planned_verifier_calls": 4,
            "select_on_B": False,
            "automatic_retry": False,
        },
    )
    outputs = {}
    for cell in MODELS:
        view = None
        tick = time.perf_counter()
        try:
            view = matched.Predictor(manifests[cell], root, training_source)
            output = view.predict(request)
            write_new(directory / (cell + "_COLD_OUTPUT.json"), output)
            verification = data.verify_answer(record, output["answer"])
            write_new(directory / (cell + "_COLD_VERIFICATION.json"), verification)
            outputs[cell] = output
        finally:
            if view is not None:
                _release_view(view, view.torch)
        write_new(
            directory / (cell + "_COLD_COST.json"),
            {
                "wall_seconds": time.perf_counter() - tick,
                "scope": "cold model load, actual generation, verifier and release",
                "model_calls": 1,
                "verifier_calls": 1,
                "full_system_cost_known": False,
            },
        )
    return {
        "record": record,
        "request": request,
        "cold": outputs,
        "cold_wall_seconds": time.perf_counter() - started,
    }


def calibrate_pool(pool, calibration, run):
    """Retain pooled generations, verify the same A, and reject loading mismatch."""
    started = time.perf_counter()
    directory = run / "A_SETUP_CALIBRATION"
    outputs = []
    pairs = {}
    for cell in MODELS:
        location = directory / (cell + "_POOL")
        location.mkdir(exist_ok=False)
        output = pool.generate(cell, calibration["request"], location)
        verification = data.verify_answer(calibration["record"], output["answer"])
        write_new(location / "VERIFICATION.json", verification)
        cold = calibration["cold"][cell]
        require(
            all(
                output[key] == cold[key]
                for key in (
                    "answer",
                    "output_token_ids",
                    "loaded_model_digest",
                    "generation_config_sha256",
                    "rendered_prompt_sha256",
                    "messages_sha256",
                )
            ),
            "cold/pool A generation differs for " + cell,
        )
        outputs.extend((cold, output))
        pairs[cell] = {
            "cold_output_digest": data.digest(cold),
            "pool_output_digest": data.digest(output),
            "active_adapter_sha256": output["active_adapter_sha256"],
            "equal": True,
        }
    result = {
        "schema": "hepta.matched-pool-calibration.v1",
        "status": "COMPLETE",
        "record_digest": data.digest(calibration["record"]),
        "request_digest": data.digest(calibration["request"]),
        "pairs": pairs,
        "model_calls": 4,
        "verifier_calls": 4,
        "calibration_verifier_source_sha256": file_hash(repo_execution.__file__),
        "calibration_verifier_scope": "original retained A repository verifier; primary upstream verification runs in the separately frozen joint runner",
        "input_tokens": sum(output["input_tokens"] for output in outputs),
        "output_tokens": sum(output["output_tokens"] for output in outputs),
        "cold_wall_seconds": calibration["cold_wall_seconds"],
        "pool_calibration_wall_seconds": time.perf_counter() - started,
        "pool_load_cost_recorded_separately": True,
        "full_system_cost_known": False,
        "monetary_cost": None,
        "energy_joules": None,
        "select_on_B": False,
        "automatic_retry": False,
    }
    write_new(directory / "RESULT.json", result)
    return result
