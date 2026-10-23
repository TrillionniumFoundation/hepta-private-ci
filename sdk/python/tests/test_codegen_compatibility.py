"""Keep the existing wire-field API when upgrading the code generator."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_omitted_move_section_keeps_the_existing_explicit_null_wire_value() -> None:
    from openai_codex.generated.v2_all import ThreadSectionMoveParams

    params = ThreadSectionMoveParams(thread_id="thread-1")
    assert params.model_dump(mode="json", by_alias=True) == {
        "beforeThreadId": None,
        "sectionId": None,
        "threadId": "thread-1",
    }


def _generated_module(tmp_path: Path, schema: dict):
    script_path = Path(__file__).parents[1] / "scripts" / "update_sdk_artifacts.py"
    spec = importlib.util.spec_from_file_location("codegen_compatibility_script", script_path)
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = script
    spec.loader.exec_module(script)
    script._annotate_schema(schema)
    source = tmp_path / "input.json"
    source.write_text(json.dumps(schema))
    generated = tmp_path / "generated.py"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "datamodel_code_generator",
            "--input",
            str(source),
            "--input-file-type",
            "jsonschema",
            "--output",
            str(generated),
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--target-python-version",
            "3.10",
            "--enum-field-as-literal",
            "one",
            "--use-title-as-name",
            "--use-annotated",
            "--formatters",
            "ruff-format",
        ],
        check=True,
    )
    generated_spec = importlib.util.spec_from_file_location(
        "codegen_compatibility_result", generated
    )
    assert generated_spec is not None and generated_spec.loader is not None
    module = importlib.util.module_from_spec(generated_spec)
    sys.modules[generated_spec.name] = module
    generated_spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("titled", [False, True])
def test_named_envelope_keeps_a_plain_required_discriminator(tmp_path: Path, titled: bool) -> None:
    schema = {
        "title": "ApiKeyAccount",
        "type": "object",
        "properties": {"type": {"type": "string", "enum": ["apiKey"]}},
        "required": ["type"],
    }
    if titled:
        schema["properties"]["type"]["title"] = "ApiKeyAccountType"
    module = _generated_module(tmp_path, schema)
    account = module.ApiKeyAccount.model_validate({"type": "apiKey"})
    assert account.type == "apiKey"
    assert type(account.type) is str
    assert account.model_dump(mode="json") == {"type": "apiKey"}
    for invalid in ({}, {"type": "different"}):
        with pytest.raises(ValidationError):
            module.ApiKeyAccount.model_validate(invalid)


def test_named_union_keeps_a_plain_single_literal_choice(tmp_path: Path) -> None:
    module = _generated_module(
        tmp_path,
        {
            "title": "Choice",
            "oneOf": [
                {"title": "ChoiceValue", "type": "string", "enum": ["auto", "concise"]},
                {"title": "NoneChoice", "type": "string", "enum": ["none"]},
            ],
        },
    )
    choice = module.Choice.model_validate("none")
    assert choice.root == "none"
    assert type(choice.root) is str
    assert choice.model_dump(mode="json") == "none"
    with pytest.raises(ValidationError):
        module.Choice.model_validate("different")
