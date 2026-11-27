"""Read-only exact-source scope check; no live fit, model or trace is loaded."""
import hashlib
import json
import math
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "v8-local-validation/source"
NAMES = (
    "proposals/localization-v3/train.py",
    "proposals/localization-v3/cores.py",
    "proposals/localization-v3/hcsn_study_support.py",
    "proposals/localization-v3/campaign.py",
    "qualification/hcsn_differentiable/training_domain.py",
    "qualification/hcsn_differentiable/network.py",
    "qualification/hcsn_differentiable/contract.py",
    "proposals/localization-v2/episodes.py",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def save(name, value):
    with (OUT / name).open("x") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main():
    archive = ROOT / "training-source-v8.zip"
    assert sha(archive) == "288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102"
    sources = {}
    with ZipFile(archive) as zipped:
        for name in NAMES:
            path = SOURCE / name
            assert path.read_bytes() == zipped.read(name)
            sources[name] = identity(path)
    plan_path = ROOT / "campaign-v2-plan.json"
    manifest_path = ROOT / "uci-cloud-prepared-v1/data-manifest.json"
    assert sha(plan_path) == "e13f97aafdaf66548f016f2dcc3a38dd7e641a2ea83d52b8bea89f4c7e0cf114"
    plan = json.loads(plan_path.read_bytes())
    assert sha(manifest_path) == plan["manifest_sha256"] == "0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb"
    manifest = json.loads(manifest_path.read_bytes())
    train = [row for row in manifest["episodes"] if row["partition"] == "train"]
    events = sum(row["events"] for row in train)
    batch, micro = plan["batch_size"], plan["micro_batch_sizes"]["hcsn"]
    captures = sum(math.ceil(min(batch, len(train)-start)/micro) for start in range(0, len(train), batch))
    epochs = plan["min_epochs"]
    retained_sample_bound = plan["trace_records"] * micro
    result = {
        "schema": "independent-v8-training-recorder-source-scope-v1",
        "source_archive": identity(archive), "sources": sources,
        "plan": identity(plan_path), "data_manifest": identity(manifest_path),
        "byte_binding": "Eight reviewed files equal the exact v8 source capsule; counts use the pinned prepared manifest, not live fit results.",
        "capture_semantics": {
            "created_after_memorization_restoration": True,
            "diagnostic_and_all_development_evaluations_captured": False,
            "main_only": True,
            "call_point": "Inside HCSNCore.forward after the complete sequence has been evaluated, before returning logits to loss/backward; all microbatches precede the one effective-batch optimizer step.",
            "update_index": "Number of completed main optimizer updates before the current attempted effective batch, zero-based; all its microbatches share this index.",
            "episode_id": "Ordered microbatch episode IDs joined with '+', interpreted with batch_indices and the update journal.",
            "capture": "One completed microbatch forward, including padded time positions in the returned trace.",
            "record": "One (capture, time position, layer) with at least one valid sample; contains vectors for every valid sample in that microbatch.",
            "record_not_a_sample_or_update": True,
            "prior": "Previous conditioned probability at the interval start, or the reset initial state at position zero; not the after-flow pre-conditioning prior.",
            "posterior": "Current probability after the interval flow and current observation conditioning.",
            "expected_events": "Conditional expected interval count from the preceding flow, before current observation conditioning.",
            "state_window": "HCSNCore resets initial_state for every independent input window; no carry across dataset windows.",
            "model_sha256": "Tensor digest of the inner ContinuousSpikingNetwork state_dict; not the full CoreStudyModel, optimizer or checkpoint file SHA.",
            "configuration_binding": "Each visit carries GridSpec, physical values, operator configuration; header binds data manifest and fit-plan SHA; complete trainer/runtime identity comes from the separate fit source ledger.",
            "content_state_in_trace": False,
            "partial_failure_scope": "Only completed capture calls are represented. A forward that fails before capture can have unrecorded internal visits; a captured forward can also precede a later failed backward or optimizer attempt.",
        },
        "padding_semantics": {
            "builder": "x=0, dt=0, y=-1 after each episode's true length; all microbatches retain the original effective-batch padded length.",
            "mask": "valid=x[...,12:24].bool().any(-1); the same mask is passed as observed and valid_mask.",
            "padding_validation": "Recorder requires masked-out dt and network predictions to be exactly zero.",
            "batch_indices": "Microbatch-local valid row indices, excluding padding.",
            "all_padding_position": "No visit record and no seen-record increment, but excluded sample-position-layer counts still increase.",
            "padded_states_excluded": "Number of masked-out sample-position-layer states over completed captures; not visit-record count.",
        },
        "caps": {
            "records": plan["trace_records"], "bytes": plan["trace_bytes"],
            "scope": "Chronological retained prefix, not random or stratified sampling.",
            "stopping": "First reached record/byte budget fixes drop_reason and stops all subsequent retention; byte check reserves 16384 bytes for footer.",
            "after_drop": "capture/model digest/range/padding/seen counters still run; individual posterior records are not retained.",
            "footer": "dropped=seen-retained; truncated iff dropped>0. Missing end footer is rejected by read_trace; no complete coverage inferred from a header alone.",
        },
        "coverage_bound": {
            "train_windows": len(train), "train_events_per_epoch": events,
            "layers": 1, "probability_coefficients": plan["hcsn_grid"]["active_cells"]+1+plan["hcsn_grid"]["phase_cells"],
            "effective_batch": batch, "microbatch": micro,
            "complete_optimizer_updates_per_epoch": math.ceil(len(train)/batch),
            "complete_capture_calls_per_epoch": captures,
            "minimum_visit_records_per_complete_epoch": math.ceil(events/micro),
            "maximum_visit_records_per_complete_epoch": captures*max(row["events"] for row in train),
            "maximum_retained_sample_position_layer_states_ignoring_byte_cap": retained_sample_bound,
            "minimum_complete_epochs": epochs,
            "main_sample_position_layer_states_at_minimum_epochs": epochs*events,
            "retained_fraction_upper_bound_at_minimum_epochs": retained_sample_bound/(epochs*events),
            "cannot_cover_even_one_full_epoch": retained_sample_bound < events,
            "byte_budget_only_tightens_bound": True,
        },
        "final_model_export": "A later fixed-window forward from a trained checkpoint is supplemental final-model evaluation, not the original training access trace. Bind checkpoint/file+tensor/config/data/window/hash identities separately.",
        "native_or_live_fit_access": False, "actual_retained_count_read": False,
        "model_forward_or_training_executed": False, "scientific_admission": "HOLD",
        "whole_training_qualification": False,
    }
    assert events == 89216 and len(train) == 356 and captures == 45
    save("RESULT.json", result)
    save("MANIFEST.json", {"files": {path.name: {"bytes": path.stat().st_size, "sha256": sha(path)} for path in OUT.iterdir() if path.is_file()}})
    print(json.dumps({"result": identity(OUT / "RESULT.json"), "manifest": identity(OUT / "MANIFEST.json"),
                      "coverage_bound": result["coverage_bound"]}, indent=2))


if __name__ == "__main__":
    main()
