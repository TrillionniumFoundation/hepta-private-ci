"""Fetch one explicitly activated, immutable repository binding; no study data."""

import argparse
import base64
import hashlib
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from supplements.parameter_field_deployment_activity_20261031 import (  # noqa: E402
    portable_common as c,
    provider,
)


def activation(args):
    supplied = [args.binding_commit, args.binding_path, args.binding_sha256]
    if any(supplied):
        c.need(all(supplied), "Dispatch requires commit, path and SHA256 together")
        value = dict(
            zip(
                ("binding_commit", "binding_path", "binding_sha256"),
                supplied,
                strict=True,
            )
        )
    else:
        path = Path(args.activation)
        if not path.exists():
            return None
        value = c.read(c.descriptor(path.absolute()), 16 * 1024)
        c.need(
            value.pop("schema", None)
            == "hepta.parameter-field.deployment-activation.1",
            "Unknown activation schema",
        )
    c.need(
        set(value) == {"binding_commit", "binding_path", "binding_sha256"}
        and re.fullmatch("[0-9a-f]{40}", value["binding_commit"] or "")
        and re.fullmatch("[0-9a-f]{64}", value["binding_sha256"] or ""),
        "Activation lacks immutable identities",
    )
    path = c.relative(value["binding_path"])
    c.need(
        str(path).startswith(
            "supplements/parameter_field_deployment_activity_20261031/bindings/"
        )
        and path.suffix == ".json"
        and path.name != "ACTIVATE.json",
        "Binding must be a separately committed JSON record",
    )
    return value


def resolve(args):
    selected = activation(args)
    if selected is None:
        return {"active": "false"}
    if args.event_name == "push":
        c.need(
            re.fullmatch("[0-9a-f]{40}", args.before_commit or ""),
            "Push ancestry is missing",
        )
        before = args.before_commit if args.before_commit != "0" * 40 else "HEAD^"
        name = "supplements/parameter_field_deployment_activity_20261031/bindings/ACTIVATE.json"
        changed = (
            c.git(c.ADDON, "diff", "--name-only", before, "HEAD", "--", name)
            .decode()
            .splitlines()
        )
        if name not in changed:
            return {"active": "false"}
    root = Path(args.output)
    c.need(not root.exists(), "Binding destination is not fresh")
    root.mkdir(parents=True, exist_ok=False)
    token = os.environ.get("GITHUB_TOKEN")
    c.need(bool(token), "Authenticated repository read is required")
    endpoint = (
        "/contents/"
        + urllib.parse.quote(selected["binding_path"], safe="/")
        + "?ref="
        + selected["binding_commit"]
    )
    response = provider.api_json(
        urllib.request.build_opener(provider.NoRedirect()), endpoint, token
    )
    c.need(
        response.get("type") == "file"
        and response.get("encoding") == "base64"
        and response.get("path") == selected["binding_path"],
        "Repository returned another binding object",
    )
    raw = base64.b64decode("".join(response["content"].split()), validate=True)
    c.need(
        len(raw) <= 256 * 1024
        and len(raw) == response["size"]
        and hashlib.sha256(raw).hexdigest() == selected["binding_sha256"],
        "Activated binding bytes differ",
    )
    destination = root / "BINDING.json"
    with destination.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    binding, item = c.load_binding(destination, selected["binding_sha256"])
    c.write(
        root / "PROVENANCE.json",
        {
            "schema": "hepta.parameter-field.binding-resolution.1",
            "selection": selected,
            "binding": item,
            "repository": provider.REPOSITORY,
            "repository_blob_sha": response["sha"],
            "scientific_payloads_requested": False,
        },
    )
    return {
        "active": "true",
        "source_commit": binding["provider"]["head_sha"],
        "binding_sha256": item["sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--activation",
        default=str(Path(__file__).with_name("bindings") / "ACTIVATE.json"),
    )
    parser.add_argument("--binding-commit", default="")
    parser.add_argument("--binding-path", default="")
    parser.add_argument("--binding-sha256", default="")
    parser.add_argument("--output", default="/work/binding")
    parser.add_argument(
        "--event-name",
        choices=("push", "workflow_dispatch"),
        default="workflow_dispatch",
    )
    parser.add_argument("--before-commit", default="")
    result = resolve(parser.parse_args())
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as stream:
            for key, value in result.items():
                stream.write(key + "=" + value + "\n")
    print(result["active"])


if __name__ == "__main__":
    main()
