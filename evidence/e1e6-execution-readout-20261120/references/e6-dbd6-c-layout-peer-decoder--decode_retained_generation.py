"""Decode the retained NoUpdate12 genesis layout; never run a Rust observer.

This narrow decoder rejects non-genesis files.  It is an independent reading of
the pinned dbd6 source, not a new authority check or a general journal verifier.
"""

import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
INPUT = BASE / "e6_owner_work/initial_observation_noupdate12_failure/c-physical"
OUTPUT = Path(__file__).resolve().parent / "PHYSICAL_LAYOUT_READOUT.json"
EXPECTED = {
    "post-a-data__c-generation.journal": (40, "d055b22f70e1d6d144deb451768dd3b80d5f7a81e6ab8fa02540689390e0be7a"),
    "post-a-witnesses__c-generation.witness": (112, "b0a7d7ff7650bf0053f1792615f3bcf58572149be2f775741439a8e59818043f"),
    "post-a-data__c-target.json": (3049, "51a105a7b0634d56d918ffd2ab8589c8136f5ba66ace49484cca47e0d3e559d9"),
    "post-a-data__c-source.json": (7383, "01534894f7bbc4b4220879af0609ec23e7f3706aad84733cc59ff9a53f37dec5"),
    "post-a-data__original-publication-material.json": (5059, "d7c67fe3c0898ee779745b91bdb5b2de16dd5c63a43a9864ab08fbc190fb5c33"),
}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, ("duplicate JSON key", key)
        result[key] = value
    return result


def compact(value):
    # These exact captured values contain only ASCII strings, integers, arrays,
    # null and booleans.  Preserve the pinned Rust struct/enum field order.
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    assert encoded.isascii()
    return encoded


def ordered(value, fields):
    assert set(value) == set(fields), (set(value), fields)
    return {name: value[name] for name in fields}


def digest(domain, value):
    return hashlib.sha256(domain + compact(value)).digest()


def main():
    assert not OUTPUT.exists(), "retain previous readout; use a new review revision"
    inputs = {}
    raw = {}
    for name, (length, expected) in EXPECTED.items():
        value = (INPUT / name).read_bytes()
        assert len(value) == length and sha(value) == expected, name
        raw[name] = value
        inputs[name] = {"path": str(INPUT / name), "bytes": length, "sha256": expected}
    target = json.loads(raw["post-a-data__c-target.json"], object_pairs_hook=unique_object)
    material = json.loads(raw["post-a-data__original-publication-material.json"], object_pairs_hook=unique_object)
    assert material["target"] == target
    generation = target["generation"]
    manifest = ordered(generation["manifest"], [
        "profile", "source_digest", "bundle_digest", "encoder", "head", "memory",
        "world_model", "decoder", "runtime_digest", "device_digest", "input_schema",
        "state_schema", "output_schema", "learning", "evolution", "max_input_bytes",
        "max_state_bytes", "max_delta_bytes", "max_prefix_bytes",
        "max_step_cost_entries", "max_ack_cost_entries",
    ])
    assert manifest["learning"]["kind"] == "frozen"
    manifest["learning"] = ordered(manifest["learning"], ["kind", "weights"])
    manifest["evolution"] = ordered(manifest["evolution"], [
        "structure", "lineage", "source_dependencies", "adoption_receipt",
    ])
    initial = ordered(generation["initial"], [
        "scope", "manifest_digest", "generation", "writer_epoch", "revision", "state", "prefix", "stopped",
    ])
    initial["scope"] = ordered(initial["scope"], ["principal_digest", "agent_id", "cell_id", "run_id"])
    config = ordered(generation, ["manifest", "initial", "source_frontier", "task_digest"])
    config["manifest"], config["initial"] = manifest, initial
    manifest_digest = digest(b"hepta.cell.backend.v2\0", manifest)
    initial_digest = digest(b"hepta.cell.runtime-state.v2\0", initial)
    config_digest = digest(b"hepta.cell.generation-owner.v2\0", [config, target["journal_records"]])
    assert bytes(initial["manifest_digest"]) == manifest_digest
    assert bytes(material["selection"]["compatibility_digest"]) == manifest_digest
    assert initial["revision"] == 0 and not initial["prefix"] and initial["stopped"] is False
    assert target["journal_records"] == 128
    assert initial["generation"] == initial["writer_epoch"] == 2
    binding = {
        "scope": initial["scope"],
        "manifest_digest": list(manifest_digest),
        "task_digest": config["task_digest"],
        "source_frontier": config["source_frontier"],
        "initial_snapshot_digest": list(initial_digest),
        "generation": initial["generation"],
        "writer_epoch": initial["writer_epoch"],
        "config_digest": list(config_digest),
    }
    journal = raw["post-a-data__c-generation.journal"]
    assert journal == b"HPTACG03" + config_digest
    witness = raw["post-a-witnesses__c-generation.witness"]
    witness_prefix = (b"HPTNWA01" + bytes(target["witness_scope"])
                      + bytes(target["witness_objective"])
                      + target["witness_generation"].to_bytes(8, "big"))
    assert witness == witness_prefix + hashlib.sha256(witness_prefix).digest()
    assert target["witness_generation"] == 2 and target["witness_records"] == 256
    # Exact lengths above leave zero journal frames and zero witness records.
    # GenerationState::new sets draining=false, pending=None, outbox=None.
    draining, pending, outbox = False, None, None
    conditions = [
        {"ordinal": 1, "expression": "generation.owner_binding() == &binding", "value": True,
         "basis": "The exact target reconstructs the actual guarded header; both original binding and observer binding are constructed from that same target."},
        {"ordinal": 2, "expression": "generation.is_drained()", "value": draining and pending is None and outbox is None,
         "basis": "Zero frames: initial reducer draining=false, pending=None, outbox=None. No Drain event is retained."},
        {"ordinal": 3, "expression": "observed.manifest_digest() == selected.manifest.digest()?", "value": bytes(initial["manifest_digest"]) == manifest_digest,
         "basis": "Exact target manifest digest equals initial and material selection compatibility digest. The original preceding native assertion also required target.generation.manifest == selected.manifest."},
        {"ordinal": 4, "expression": "observed.snapshot().revision == 0", "value": initial["revision"] == 0},
        {"ordinal": 5, "expression": "observed.snapshot().prefix.is_empty()", "value": not initial["prefix"]},
        {"ordinal": 6, "expression": "!observed.snapshot().stopped", "value": not initial["stopped"]},
        {"ordinal": 7, "expression": "observed.pending_request_digest().is_none()", "value": pending is None},
        {"ordinal": 8, "expression": "observed.pending_output().is_none()", "value": outbox is None},
    ]
    result = {
        "schema": "e6-retained-generation-layout-review-v1",
        "source_commit": "dbd6a00992b60f4b33e8f10c2defda031d123bcb",
        "kind": "INDEPENDENT_STATIC_DECODE_OF_RETAINED_BYTES",
        "decoder": {"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__).read_bytes())},
        "inputs": inputs,
        "target_equals_material_target": True,
        "journal": {"bytes": len(journal), "magic": "HPTACG03", "header_config_digest": config_digest.hex(),
                    "exact_target_header_match": True, "frame_count": 0, "drain_event_count": 0, "head": None},
        "witness": {"bytes": len(witness), "magic": "HPTNWA01", "header_context_and_checksum_match": True,
                    "record_count": 0, "current_anchor": None, "generation": target["witness_generation"]},
        "digests": {"manifest": manifest_digest.hex(), "initial_snapshot": initial_digest.hex(),
                    "owner_binding": digest(b"hepta.cell.generation-owner-binding.v1\0", binding).hex()},
        "state": {"revision": initial["revision"], "prefix_bytes": len(initial["prefix"]),
                  "stopped": initial["stopped"], "draining": draining, "pending_request": pending, "pending_output": outbox},
        "original_assertion_conditions": conditions,
        "false_condition_ordinals": [c["ordinal"] for c in conditions if not c["value"]],
        "all_eight": all(c["value"] for c in conditions),
        "conclusion": "The retained C Generation is an exact genesis with no Drain. Under the pinned reducer, only is_drained is false among the original eight conditions.",
        "limits": [
            "No new Rust observer, current authorization, source/cell recovery, model, native test, host call or gate executed.",
            "The original selected-manifest identity premise is from the original earlier native assertion plus captured material; this decoder does not authenticate its signature anew.",
            "These after-exit bytes and original assertion locate the retained-state failure; they do not establish the exact time of a missing mutation.",
            "This is not independent proof of Root64 acceptance, completed whole parent, cold D or FinalUse.",
        ],
    }
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(OUTPUT), "sha256": sha(OUTPUT.read_bytes()),
                      "frame_count": 0, "witness_record_count": 0, "conditions": [c["value"] for c in conditions]}, indent=2))


if __name__ == "__main__":
    main()
