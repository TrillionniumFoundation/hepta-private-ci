"""Create-only CPU qualification carrier builder; no model or provider calls."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

PACKAGE = "qualification/hcsn_regenerative/cpu_qualification_v1/"
REUSED_PACKAGE = "qualification/hcsn_regenerative/colab_qualification_v4/"
CONTROLS = ("__init__.py", "qualification_runner.py", "build_qualification.py", "evidence_guard.py", "freeze_cpu.py", "RESOURCE_AMENDMENT.json", "test_cpu_controls.py")
REUSED = ("__init__.py", "qualification_runner.py", "asset_transport.py")
STUDY_ID = "hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-cpu-v1"
SOURCE35_SHA256 = "ad130bd8cd307ae4e6971a11978863ed6771ccc269b1f40b468d530f1f9f9c4e"
BUNDLE = "inputs/prior-qualified-bundle/operators-s81.npz"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def pin(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def commands(request_id):
    prefix = "qualification.hcsn_regenerative."
    return [
        dict(name="capability", timeout_seconds=60, args=["-m", prefix+"cpu_qualification_v1.qualification_runner", "--capability", "--request-id", request_id, "--output", "evidence/capability.json"]),
        dict(name="fv-unit", timeout_seconds=120, args=["-m", "unittest", prefix+"tests.test_distribution", "-v"], unit_methods_expected=8),
        dict(name="fv-audit-cpu", timeout_seconds=300, args=["-m", prefix+"run_distribution_audit", "--device", "cpu", "--output", "evidence/fv-audit-cpu.json"], result_json="evidence/fv-audit-cpu.json", accepted_statuses=["pass"], checks_expected=12, check_key="pass_"),
        dict(name="fixed-renewal-audit", timeout_seconds=120, args=["-m", prefix+"run_fixed_renewal_audit", "--output", "evidence/fixed-renewal-audit-s81.json"], result_json="evidence/fixed-renewal-audit-s81.json", accepted_statuses=["BOUNDED_FP64_CONSTRUCTION_CHECKS_PASS"]),
        dict(name="resolution-s81-fixed", timeout_seconds=300, args=["-m", "resolution_scope.run_resolution_probe", "--device", "cpu", "--output", "evidence/resolution-s81-fixed.json"], result_json="evidence/resolution-s81-fixed.json", accepted_statuses=["complete"]),
        dict(name="mechanism-unit", timeout_seconds=120, args=["-m", "unittest", prefix+"tests.test_mechanism_training", "-v"], unit_methods_expected=13),
        dict(name="mechanism-graph-cpu", timeout_seconds=120, args=["-m", prefix+"mechanism_qualify", "--bundle", BUNDLE, "--device", "cpu", "--output", "evidence/mechanism-graph-cpu.json"], result_json="evidence/mechanism-graph-cpu.json", accepted_statuses=["pass"], checks_expected=47, check_key="passed"),
        dict(name="mechanism-sequence-cpu", timeout_seconds=300, args=["-m", prefix+"mechanism_sequence_probe", "--bundle", BUNDLE, "--device", "cpu", "--output", "evidence/sequence-cpu"], result_json="evidence/sequence-cpu/receipt.json", accepted_statuses=["pass"], checks_expected=42, check_key="passed"),
    ]


BOOTSTRAP = r'''
import base64, hashlib, io, json, os, stat, sys, tempfile, time, zipfile
from pathlib import Path, PurePosixPath
payload_start, payload_unix = time.monotonic(), time.time()
public = Path.cwd()
if any((public/n).exists() for n in ("execution.json","source-manifest.json","outer-timing.json","suite-artifacts.zip","artifact-manifest.json")):
    raise FileExistsError("New output namespace required")
asset = base64.b64decode(ASSET_B64, validate=True)
if hashlib.sha256(asset).hexdigest() != CONFIG["asset_zip"]["sha256"] or len(asset) != CONFIG["asset_zip"]["bytes"]:
    raise ValueError("Embedded carrier bytes differ")
members = dict(CONFIG["source_files"], **CONFIG["control_source_files"], **CONFIG["reused_control_source_files"], **CONFIG["input_files"])
work = Path(tempfile.mkdtemp(prefix="hcsn-cpu-qualification-"))
with zipfile.ZipFile(io.BytesIO(asset)) as archive:
    if archive.testzip() is not None or len(archive.namelist()) != len(members) or set(archive.namelist()) != set(members):
        raise ValueError("Carrier CRC/roster differs")
    for name, expected in sorted(members.items()):
        rel=PurePosixPath(name); info=archive.getinfo(name)
        if rel.is_absolute() or ".." in rel.parts or "\\" in name or info.is_dir() or stat.S_ISLNK(info.external_attr>>16):
            raise ValueError("Unsafe carrier member")
        raw=archive.read(name)
        if {"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()} != expected:
            raise ValueError("Carrier member bytes differ")
        path=work/rel; path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("xb") as stream: stream.write(raw)
with (work/"qualification-config.json").open("x") as stream:
    json.dump(CONFIG, stream, sort_keys=True, separators=(",",":"), allow_nan=False)
os.chdir(work); sys.path.insert(0,str(work))
from qualification.hcsn_regenerative.cpu_qualification_v1.qualification_runner import run_qualification
raise SystemExit(run_qualification(work/"qualification-config.json", public, payload_start, payload_unix))
'''


def build(source_root, carrier_path, specification_path, output):
    spec = json.loads(specification_path.read_bytes())
    sources, inputs = spec["source_files"], spec["input_files"]
    if len(sources) != 35 or len(inputs) != 2 or pin(canonical(sources))["sha256"] != SOURCE35_SHA256:
        raise ValueError("Original source35/two-input identity differs")
    request = spec["request_id"]
    stem = re.sub(r"[^a-z0-9-]+", "-", request.lower()).strip("-")[:18]
    if not 1 <= len(request) <= 80 or not stem or stem.endswith("-") or "--" in stem:
        raise ValueError("Unsafe installed slug stem")
    controls = {PACKAGE+n: (source_root/(PACKAGE+n)).read_bytes() for n in CONTROLS}
    reused = {REUSED_PACKAGE+n: (source_root/(REUSED_PACKAGE+n)).read_bytes() for n in REUSED}
    if {name:pin(raw) for name,raw in reused.items()} != spec["reused_control_source_files"]:
        raise ValueError("Reused supervision helper bytes differ")
    carrier = carrier_path.read_bytes()
    if pin(carrier) != spec["carrier"]:
        raise ValueError("Exact historical static input carrier differs")
    contents = {}
    with zipfile.ZipFile(io.BytesIO(carrier)) as archive:
        if archive.testzip() is not None or len(set(archive.namelist())) != len(archive.namelist()):
            raise ValueError("Carrier CRC/duplicates")
        for name, expected in dict(sources, **inputs).items():
            raw = archive.read(name)
            if pin(raw) != expected:
                raise ValueError("Original source/input bytes differ")
            contents[name] = raw
    contents.update(controls); contents.update(reused)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(contents.items()):
            item=zipfile.ZipInfo(name,(1980,1,1,0,0,0));item.create_system=3
            item.external_attr=(stat.S_IFREG|0o600)<<16
            archive.writestr(item,raw,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    asset = buffer.getvalue()
    config = dict(schema="hcsn-kaggle-cpu-qualification-config-v1", study_id=STUDY_ID,
        request_id=request, provider_timeout_seconds=3000, commands=commands(request),
        source_files=sources, source_set_sha256=SOURCE35_SHA256, input_files=inputs,
        control_source_files={n:pin(b) for n,b in controls.items()},
        reused_control_source_files={n:pin(b) for n,b in reused.items()},
        external_budget=spec["external_budget"], asset_zip=pin(asset),
        execution_source_scope=dict(scientific_files=35, declared_new_control_files=7,
            reused_supervision_files=3, actual_scientific_subset_unchanged=True,
            numerical_credit_does_not_cover_future_formal_controls=True))
    payload = ("CONFIG="+repr(config)+"\nASSET_B64="+repr(base64.b64encode(asset).decode())+"\n"+BOOTSTRAP).encode()
    compile(payload,"cpu-qualification-payload.py","exec")
    if len(payload)>2*1024*1024:
        raise ValueError("Installed adapter source limit exceeded")
    manifest = dict(config, schema="hcsn-kaggle-cpu-qualification-prepared-v1",
        accelerator="cpu", account_selector=spec["account_selector"], expected_username=spec["expected_username"],
        expected_user_id=spec["expected_user_id"], artifact_budget_bytes=67108864,
        stage_wall_budget_seconds=1440, payload=pin(payload), builder=pin(Path(__file__).read_bytes()),
        bootstrap=pin(BOOTSTRAP.encode()), specification=pin(specification_path.read_bytes()),
        installed_slug_stem=stem, kernel_sources=[spec["external_budget"]["notebook_ref"]],
        dataset_sources=[], competition_sources=[], model_sources=[],
        formal_training_fits=0, external_budget_optimizer_updates_rerun=0,
        provider_exit_zero_scope="Evidence export only, not numerical admission.")
    output.mkdir(parents=True,exist_ok=False)
    for name, raw in (("assets.zip",asset),("cpu-qualification-payload.py",payload),
                      ("qualification-config.json",canonical(config)+b"\n"),
                      ("PREPARED_MANIFEST.json",canonical(manifest)+b"\n")):
        with (output/name).open("xb") as stream: stream.write(raw)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("source-root","carrier","specification","output"):
        parser.add_argument("--"+name,required=True,type=Path)
    args=parser.parse_args()
    result=build(args.source_root,args.carrier,args.specification,args.output)
    print(json.dumps({k:result[k] for k in ("study_id","request_id","payload","asset_zip","installed_slug_stem")},sort_keys=True))


if __name__=="__main__":
    main()
