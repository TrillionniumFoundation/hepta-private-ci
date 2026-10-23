"""Keep the existing wire-field API when upgrading the code generator."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError, field_validator


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


def test_omitted_structured_default_keeps_subclass_validators_explicit_only() -> None:
    from openai_codex.generated.v2_all import MigrationDetails

    calls = []

    class ReviewedMigration(MigrationDetails):
        @field_validator("commands", mode="before")
        @classmethod
        def explicit_commands(cls, value):
            calls.append(value)
            raise ValueError("explicit commands rejected")

    assert ReviewedMigration().commands == []
    assert calls == []
    with pytest.raises(ValidationError, match="explicit commands rejected"):
        ReviewedMigration(commands=[])
    assert calls == [[]]


@pytest.fixture(scope="module")
def generated_default_sources(tmp_path_factory):
    # Invoke the real pinned runtime schema and the production generator path;
    # all output stays in this temporary SDK, including negative mutations.
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location(
        "default_validation_codegen", root / "scripts" / "update_sdk_artifacts.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = script
    spec.loader.exec_module(script)
    directory = tmp_path_factory.mktemp("generated-defaults")
    schema = script.generate_schema_from_pinned_runtime(directory / "schema")
    script.sdk_root = lambda: directory
    restore = script._preserve_default_validation
    observed = {}

    def capture(path):
        observed["before"] = path.read_text()
        restore(path)
        observed["after"] = path.read_text()

    script._preserve_default_validation = capture
    script.generate_v2_all(schema)
    script._preserve_default_validation = restore
    return script, observed


def test_real_generator_restores_only_the_17_field_validation_keywords(
    generated_default_sources,
) -> None:
    _, observed = generated_default_sources
    before = ast.parse(observed["before"])
    removed = 0
    for node in ast.walk(before):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Field"
        ):
            for keyword in list(node.keywords):
                if keyword.arg == "validate_default":
                    assert isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                    node.keywords.remove(keyword)
                    removed += 1
    assert removed == 17
    assert ast.dump(before, include_attributes=False) == ast.dump(
        ast.parse(observed["after"]), include_attributes=False
    )


@pytest.mark.parametrize(
    "old,new",
    [
        ("commands: Annotated", "renamed_commands: Annotated"),
        ("list[CommandMigration] | None", "list[Any] | None"),
        ("Field(validate_default=True)] = []", "Field(validate_default=True)] = [None]"),
        ("Field(validate_default=True)", "Field(validate_default=False)"),
        ("Field(validate_default=True)", "Field()"),
        ("Field(validate_default=True)", "Field(validate_default=True, validate_default=True)"),
        (
            "    commands: Annotated",
            "    extra: Annotated[list[CommandMigration] | None, Field(validate_default=True)] = []\n"
            "    commands: Annotated",
        ),
    ],
)
def test_changed_default_validation_shape_refuses_without_writing(
    generated_default_sources, tmp_path: Path, old: str, new: str
) -> None:
    script, observed = generated_default_sources
    assert old in observed["before"]
    source = observed["before"].replace(old, new, 1)
    path = tmp_path / "changed.py"
    path.write_text(source)
    with pytest.raises(RuntimeError, match="default validation"):
        script._preserve_default_validation(path)
    assert path.read_text() == source


def test_default_validation_spans_preserve_unicode_before_and_inside_calls(
    generated_default_sources, tmp_path: Path
) -> None:
    script, observed = generated_default_sources
    source = (
        observed["before"]
        .replace(
            "    commands: Annotated",
            "    note = 'é😀'; commands: Annotated",
            1,
        )
        .replace(
            "Field(validate_default=True)", 'Field(description="é😀", validate_default=True)', 1
        )
    )
    path = tmp_path / "unicode.py"
    path.write_text(source)
    script._preserve_default_validation(path)
    assert "note = 'é😀'" in path.read_text()
    assert "é😀" in path.read_text()
