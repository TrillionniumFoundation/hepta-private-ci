"""Prepare exact old evidence and only original seed137 public inputs.

No tensor-library imports, model execution, root solving, fitting, test-array
extraction, or use of source83 quality. Existing bounded parsing/fetch routines
are imported only after their complete original source identity is verified.
"""
import ast
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
import zipfile

HERE = Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(raw, spec):
    if len(raw) != spec["bytes"] or sha(raw) != spec["sha256"]:
        raise ValueError("frozen public or prior evidence bytes differ")
    return raw


def save(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write(path, value):
    save(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n").encode())


def main():
    if len(sys.argv) != 6:
        raise SystemExit("prepare_public.py BINDING TRANSFER OLD_ZIP NEW_PREPARED NEW_RECEIPT")
    binding_path, transfer, archive_path, destination, receipt_path = (Path(v).resolve() for v in sys.argv[1:])
    started, cpu = time.monotonic(), time.process_time()
    try:
        binding_raw = binding_path.read_bytes()
        binding = json.loads(binding_raw)
        if binding["status"] != "FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW" or binding["seed"] != 137:
            raise ValueError("unreviewed repair preparation")
        for name, item in binding["adapter_files"].items():
            checked((HERE/name).read_bytes(), item)
        for name, item in binding["transfer_files"].items():
            checked((transfer/name).read_bytes(), item)
        module_spec = importlib.util.spec_from_file_location("frozen_transfer_preparer", transfer/"prepare_public.py")
        old = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(old)
        cache_raw = checked((HERE/"CACHED_ROOT_BINDING_V1.json").read_bytes(), binding["cache_binding"])
        cache = json.loads(cache_raw)
        original_raw = checked(archive_path.read_bytes(), binding["predecessor_artifact"])
        archive = old.members(original_raw, cache["artifact_files"], 1048576)
        for name, item in cache["artifact_files"].items():
            checked(archive.read(name), item)
        # Full prior ZIP is checked; only the declared seed137 evidence and
        # source47 unavailable-method receipt are materialized as inputs.
        destination.mkdir(parents=True, exist_ok=False)
        cached = destination/"cached137"
        cached.mkdir(exist_ok=False)
        for name, item in cache["parent_files"].items():
            save(cached/name, checked(archive.read("supervised/parent137/"+name), item))
        prior = json.loads((cached/"RESULT.json").read_text())
        if (prior["status"] != "PARENT_ABORTED" or prior["failed_phase"] != "RERUN_PROGRAM"
                or prior["retry_permitted"] is not False or prior["source_copy_available"] is not False):
            raise ValueError("original failure or unavailable COPY identity differs")
        source47_name = "source47_abstention/RESULT.json"
        source47_raw = checked(archive.read(source47_name), cache["artifact_files"][source47_name])
        source47 = json.loads(source47_raw)
        if (source47["status"] != "ABSTAIN_OR_ABORTED"
                or source47["error"] != "Abstain('MULTIPLE_CERTIFIED_ROOTS')"
                or any(source47["counts"][k] != 0 for k in ("forwards", "backwards", "analytic_solves", "optimizer_steps"))):
            raise ValueError("original source47 no-candidate condition differs")
        save(destination/"SOURCE47_RESULT.json", source47_raw)
        manifest = json.loads(checked((HERE/"public_inputs_seed137.json").read_bytes(), binding["parent_manifest"]))
        public, receipts = {}, []
        for item in manifest["inputs"]:
            spec = dict(item, commit=manifest["source_commit"])
            raw = old.fetch(spec)
            public[Path(item["path"]).name] = raw
            receipts.append(dict(path=item["path"], bytes=len(raw), sha256=sha(raw), git_blob=item["git_blob"]))
        contract = old.fetch(manifest["data_contract"])
        erratum = json.loads(contract)["source_integrity_erratum"]
        if (erratum["excluded_actor_emotion"] != [[7, 3]]
                or erratum["expected_queries"] != dict(train=80, dev=32, retain=28, test=48)):
            raise ValueError("original public source-integrity erratum differs")
        receipts.append(dict(manifest["data_contract"], source_integrity_verified=True))
        payload_outer = old.members(public["t4_payload.zip"], {"t4_submitted.py"})
        submitted = checked(payload_outer.read("t4_submitted.py"), manifest["payload_script"])
        literals = [node.value for node in ast.walk(ast.parse(submitted))
            if isinstance(node, ast.Constant) and isinstance(node.value, bytes)]
        if len(literals) != 1:
            raise ValueError("exact static payload bytes literal differs")
        inner = base64.b64decode(literals[0], validate=True)
        if sha(inner) != manifest["inner_zip_sha256"]:
            raise ValueError("original static inner ZIP differs")
        listing = {item["path"]:item for item in manifest["payload_members"]}
        payload = old.members(inner, listing)
        parent = destination/"parent137"
        parent.mkdir(exist_ok=False)
        save(parent/"data_contract.json", contract)
        for name, item in listing.items():
            if name == "data/test.npz":
                continue
            raw = checked(payload.read(name), item)
            target = parent/"source"/name
            target.parent.mkdir(parents=True, exist_ok=True)
            save(target, raw)
        checkpoints = zipfile.ZipFile(io.BytesIO(public["selected_checkpoints.zip"]))
        if len(checkpoints.namelist()) != len(set(checkpoints.namelist())):
            raise ValueError("duplicate checkpoint ZIP names")
        spec = manifest["checkpoint"]
        raw = checked(checkpoints.read(spec["archive_member"]), spec)
        seal = checkpoints.read(spec["seal_member"])
        if sha(seal) != spec["seal_sha256"] or json.loads(seal)["centered_137"] != sha(raw):
            raise ValueError("original public checkpoint seal differs")
        save(parent/"parent.pt", raw)
        history = json.loads(public["lowlevel_results.json"])
        fit = [r for r in history["rows"] if r["mode"]=="fit" and r["arm"]=="centered" and r["seed"]==137]
        evaluation = [r for r in history["rows"] if r["mode"]=="eval" and r["arm"]=="centered" and r["seed"]==137]
        if len(fit)!=1 or len(evaluation)!=1 or fit[0]["checkpoint"] != spec["sha256"]:
            raise ValueError("unique historical parent identity differs")
        write(parent/"golden_retain.json", evaluation[0]["retain"])
        golden = checked((parent/"golden_retain.json").read_bytes(), manifest["golden_retain_export"])
        prepared = dict(schema="hepta.transfer137.repair-public-prepared.v1", seed=137,
            binding_sha256=sha(binding_raw), input_manifest_sha256=binding["parent_manifest"]["sha256"],
            cache_binding_sha256=sha(cache_raw), inputs=receipts, parent_sha256=sha(raw),
            golden_retain_sha256=sha(golden), original_artifact_sha256=sha(original_raw),
            original_seed137_failure_sha256=sha((cached/"RESULT.json").read_bytes()),
            old_evidence_not_modified=True, old_qualification_reused=True, other_parent_executed=False,
            test_npz_extracted=False, historical_test_fields_used=False, submitted_script_executed=False,
            model_calls=0, fits=0, root_calls=0, actual_public_downloads=4)
        write(parent/"PREPARED.json", prepared)
        write(destination/"PREPARED.json", dict(prepared, cpu_seconds=time.process_time()-cpu,
            wall_seconds=time.monotonic()-started, cache_files=len(cache["parent_files"])))
        write(receipt_path, dict(status="PREPARED", model_calls=0, fits=0, root_calls=0,
            retries=0, aggregate_preparation_sha256=sha((destination/"PREPARED.json").read_bytes())))
    except BaseException as error:
        if not receipt_path.exists():
            write(receipt_path, dict(status="FAILED_BEFORE_MODEL", failure_type=type(error).__name__,
                model_calls=0, fits=0, root_calls=0, retries=0, partial_inputs_retained=True,
                cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-started))
        # HTTP exceptions may contain signed or transient transport information.
        raise RuntimeError("public repair preparation failed; no retry; inspect typed receipt") from None


if __name__ == "__main__":
    main()
