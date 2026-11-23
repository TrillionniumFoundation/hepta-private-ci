"""Read registered training inputs of the Cells participating in a frozen Circuit."""

from pathlib import Path

from . import adoption, chat_protocol, coding_sft, data, paired_cold
from .paired_intake import digest_field, require, sha


def training_inputs(bundle, materials):
    """Historical LoRA fixture receipts have to be committed before the paired freeze.

    The normal source-training manifest already carries its registered input
    catalogue. A base checkpoint has no study fit. A historical tuned Cell lacking
    either original binding cannot support this subsequent-input admission.
    """
    raw_hashes = set()
    token_hashes = set()
    registered = bundle.get("consumer_cell_training_receipts", {})
    require(isinstance(registered, dict) and set(registered) <= set(bundle["models"]),
            "invalid Circuit training receipt inventory")
    for key, model in bundle["models"].items():
        if key not in registered:
            exposure = model.get("paired_source_exposure")
            require((model.get("parent") is None and not model["runtime"].get("adapter_directory"))
                    or isinstance(exposure, dict) and exposure.get("known_prompt_hashes")
                    and exposure.get("input_ids_sha256"), "tuned Circuit Cell lacks registered training inputs")
            continue
        # Historical test_circuit_bundle saves its single actual SGD training receipt
        # next to the original adapter. New source fits use paired_source_exposure.
        adapter = model["runtime"]["adapter_directory"]
        require(isinstance(adapter, str) and adapter, "adapted Circuit Cell required")
        path = coding_sft.bound_file(materials, str(Path(adapter) / "TRAINING.json"))
        receipt = adoption.read_json(path)
        pred = receipt["corrected_prediction"]
        require(data.digest(receipt) == digest_field(registered[key])
                and receipt["scope"] == "authored_development"
                and receipt["parameters"] == "one step SGD on the LoRA output head"
                and receipt["child"] == pred["loaded_model_digest"] == data.digest(model)
                and receipt["parent"] == model["parent"]
                and receipt["parameter_before"] != receipt["parameter_after"]
                and receipt["initial_verification"]["success"] is False
                and receipt["corrected_verification"]["success"] is True,
                "original single-step Circuit Cell training receipt differs")
        prompt = receipt["input"]
        tok = paired_cold.frozen_tokenizer(model, materials)
        rendered = coding_sft.prompt_text(prompt, tok, chat_protocol.NATIVE)
        ids = tok.encode(rendered, add_special_tokens=False)
        require(pred["input_sha256"] == sha(prompt.encode())
                and pred["rendered_input_sha256"] == sha(rendered.encode())
                and pred["input_tokens"] == len(ids), "Circuit Cell training input differs")
        raw_hashes.add(sha(prompt.encode()))
        token_hashes.add(data.digest(ids))
    return raw_hashes, token_hashes
