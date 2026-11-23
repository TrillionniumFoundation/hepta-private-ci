"""Local selection, fresh-process coding inference, and token-level readback."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import adoption, chat_protocol, coding_sft, data, paired_cold, paired_source
from .paired_intake import require, sha

OFFLINE = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
}


def selection(folder, pair, req, materials, *, create=False):
    """Only the local paired owner may produce the comparison consumed for selection."""
    directory = folder / "selection"
    if create and not directory.exists():
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            new = Path(tmp) / "cold"
            subprocess.run(
                [sys.executable, "-m", "cell_experiments.paired_cold",
                 str(folder.parent / "paired.json"), pair, str(materials), str(new)],
                env={**os.environ, **OFFLINE}, check=True,
                timeout=2 * req["timeout_seconds"] + 30,
            )
            os.rename(new, directory)
            paired_source.sync_directory(folder)
    result = adoption.read_json(directory / "RESULT.json")
    require(
        result["schema"] == "hepta.paired-cold.result.v1"
        and result["request_sha256"] == pair
        and data.digest(adoption.read_json(directory / "REQUEST.json")) == pair,
        "local selection differs from the released pair",
    )
    outcomes = {}
    for i, arm in enumerate(paired_cold.ARMS):
        model = req[arm]
        native = paired_cold.verify_materials(model, materials)
        end = adoption.read_json(directory / arm / "END.json")
        ordered = [(panel, item) for panel in paired_cold.PANELS for item in req[panel]]
        require(
            end == result["cold_receipts"][i] and end["arm"] == arm
            and end["request_sha256"] == pair and end["model_digest"] == native
            and len(end["row_hashes"]) == len(ordered),
            "original cold arm differs",
        )
        for n, (panel, record) in enumerate(ordered):
            raw = adoption.read_json(directory / arm / f"{n:04d}.json")
            pred = raw["prediction"]
            score = data.verify_answer(record, pred["answer"])
            require(
                data.digest(raw) == end["row_hashes"][n]
                and raw["task_sha256"] == data.digest(record) and raw["panel"] == panel
                and raw["outcome"] == score and pred["pid"] == end["pid"]
                and pred["loaded_model_digest"] == native,
                "original cold row, model, or score differs",
            )
            outcomes[panel, n, arm] = score["success"]
    future = [n for panel, n, arm in outcomes if panel == "future" and arm == "parent"]
    retained = [n for (panel, n, arm), passed in outcomes.items()
                if panel == "retention" and arm == "parent" and passed]
    delta = sum(int(outcomes["future", n, "candidate"]) - int(outcomes["future", n, "parent"])
                for n in future)
    require(delta > 0 and retained and all(outcomes["retention", n, "candidate"] for n in retained)
            and result["future_success_count_delta"] == delta and result["old_parent_successes_preserved"] is True,
            "local evaluation did not select a retained, improved candidate")
    return data.digest(result)


def encoding(req, task, materials):
    require(isinstance(task, dict) and set(task) in ({"input"}, {"input", "messages"})
            and isinstance(task["input"], str) and task["input"], "expected only a model-visible task")
    model = req["candidate"]
    tokenizer = paired_cold.frozen_tokenizer(model, materials)
    protocol = chat_protocol.protocol_name(model["runtime"])
    rendered = coding_sft.prompt_text(task["input"], tokenizer, protocol, task.get("messages"))
    ids = tokenizer.encode(rendered, add_special_tokens=False)
    require(0 < len(ids) <= model["runtime"]["max_input_tokens"], "subsequent input exceeds budget")
    # Reuse the same A, catalog, historical panel, and tokenizer-collision exclusions.
    excluded = set(paired_cold.token_inputs(req, model, materials).values())
    exposure = model.get("paired_source_exposure", {})
    excluded.update(exposure.get("input_ids_sha256", []))
    from . import prospective_exposure
    catalogs = list(exposure.get("registered_catalogs", []))
    catalog = prospective_exposure.catalog_for(model)
    if catalog is not None:
        catalogs.append(catalog)
    known = set(exposure.get("known_prompt_hashes", []))
    for catalog in catalogs:
        known.update(item["prompt_sha256"] for item in catalog["known_inputs"])
        excluded.update(item["input_ids_sha256"] for item in catalog["known_inputs"])
    require(data.digest(ids) not in excluded and sha(task["input"].encode()) not in known,
            "subsequent task repeats a known prompt or effective input")
    return tokenizer, rendered, ids


def inspect(req, task, materials, pred):
    tokenizer, rendered, ids = encoding(req, task, materials)
    model = req["candidate"]
    produced = pred["output_ids"]
    require(isinstance(produced, list) and all(type(t) is int and 0 <= t < len(tokenizer) for t in produced)
            and 0 < len(produced) <= model["runtime"]["max_new_tokens"]
            and pred["loaded_model_digest"] == data.digest(model)
            and pred["input_sha256"] == sha(task["input"].encode())
            and pred["rendered_input"] == rendered
            and pred["rendered_input_sha256"] == sha(rendered.encode())
            and pred["input_ids"] == ids and pred["input_ids_sha256"] == data.digest(ids)
            and pred["input_tokens"] == len(ids) and pred["output_tokens"] == len(produced)
            and pred["answer"] == tokenizer.decode(produced, skip_special_tokens=True)
            and pred["external_effect_executed"] is False, "original model output or token readback differs")
    return pred["answer"].encode("utf-8")


def worker(materials, path):
    """This process receives a private task and a manifest, never the issuer descriptors."""
    payload = adoption.read_json(path / "worker-input.json")
    model = payload["model"]
    require(coding_sft.verify_model(model, materials) == payload["candidate"], "wrong cold candidate")
    p = coding_sft.load_predictor(model, materials)
    try:
        pred = p.predict({"task": payload["task"]}, retain_encoding=True)
    finally:
        p.close()
    require(coding_sft.verify_model(model, materials) == payload["candidate"], "model changed during use")
    coding_sft.write_new(path / "worker-output.json", dict(nonce=payload["nonce"], prediction=pred))


if __name__ == "__main__":
    worker(Path(sys.argv[1]), Path(sys.argv[2]))
