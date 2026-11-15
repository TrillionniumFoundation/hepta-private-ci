"""Validate complete observations and native frames without replacing results."""
import re
import struct

from patch_effects_oracle import observations as effects

require = effects.require
number = effects.number
unhex = effects.unhex


def parse(raw):
    require(raw.endswith(b"\n"), "observer omitted final newline")
    values = {}
    for line in raw[:-1].split(b"\n"):
        key, separator, value = line.partition(b"=")
        require(separator, "malformed observer line")
        key, value = key.decode("ascii"), value.decode("ascii")
        require(key not in values, "duplicate observer field")
        if key.endswith("_hex"):
            unhex(value)
        values[key] = value
    require(values.get("protocol") == "HPAO0001" and
            values.get("observation_complete") == "true", "incomplete application observation")
    return values


def validate_fields(values, case, request, root):
    import os
    require(unhex(values["request_hex"]) == request, "actual request echo differs")
    require(unhex(values["fixture_root_hex"]) == os.fsencode(root), "actual fixture path differs")
    require(unhex(values["case_name_hex"]) == case["case"].encode() and
            number(values["entry"]) == case["entry"], "actual public entry/case differs")
    require(unhex(values["sandbox_json_hex"]) == case["sandbox_json"].encode() and
            values["sandbox_present"] == str(bool(case["sandbox_json"])).lower(),
            "actual sandbox context differs")
    mode = ("NormalizeToLf", "PreserveLineEndings")[case["mode"]]
    follow = str(bool(case["follow_symlinks"])).lower()
    require(unhex(values["options_debug_hex"]) ==
            f"ApplyPatchOptions {{ update_file_mode: {mode}, follow_symlinks: {follow} }}".encode(),
            "actual default or explicit options differ")
    require(values["filesystem_result_substitution"] == "false", "filesystem wrapper substituted a result")
    required = {"protocol", "request_hex", "entry", "case_name_hex", "fixture_root_hex",
        "cwd_debug_hex", "patch_hex", "direct_hunks_debug_hex", "options_debug_hex",
        "sandbox_present", "sandbox_json_hex", "sandbox_debug_hex",
        "filesystem_result_substitution", "before_entries", "after_entries",
        "status", "delta_exact", "delta_changes", "delta_debug_hex", "writer_events",
        "fs_events", "native_calls", "observation_complete"}
    for stream in ("stdout", "stderr"):
        style, policy, point, fragment = case[stream + "_policy"]
        expected = f"Policy {{ style: {style}, mode: {policy}, point: {point}, fragment: {fragment} }}"
        require(unhex(values[stream + "_policy_debug_hex"]) == expected.encode(),
                "actual writer policy differs")
        required.update(stream + suffix for suffix in
                        ("_policy_debug_hex", "_hex", "_writes", "_formats", "_flushes"))
    require(values["status"] in {"success", "error"} and
            values["delta_exact"] in {"true", "false"}, "invalid public result")
    if values["status"] == "error":
        required.update(("failure_debug_hex", "kind", "display_hex", "debug_hex", "error_chain_count"))
        require(values["kind"] in {"ParseError", "IoError", "ComputeReplacements", "PathUri",
                                   "ImplicitInvocation"}, "unknown public error variant")
        require(0 < number(values["error_chain_count"]) < 64, "invalid complete error-chain count")
        for i in range(number(values["error_chain_count"])):
            prefix = "error_chain_" + str(i)
            required.update((prefix + "_display_hex", prefix + "_debug_hex"))
            if prefix + "_io_kind" in values:
                required.update((prefix + "_io_kind", prefix + "_raw_os_error", prefix + "_inner_present"))
                require(values[prefix + "_inner_present"] in {"true", "false"}, "invalid io inner flag")
    for prefix in ("before", "after"):
        count = number(values[prefix + "_entries"])
        require(count >= 1, "missing actual fixture snapshot")
        required.update(prefix + "_" + str(i) + "_hex" for i in range(count))
    for prefix, count in (("fs_event_", "fs_events"), ("writer_event_", "writer_events")):
        required.update(prefix + str(i) + "_hex" for i in range(number(values[count])))
    for i in range(number(values["delta_changes"])):
        prefix = "delta_" + str(i)
        required.update((prefix + "_path_debug_hex", prefix + "_path_native_hex", prefix + "_kind"))
        kind = values[prefix + "_kind"]
        if kind in {"Add", "Delete"}:
            required.add(prefix + "_content_hex")
        if kind == "Add":
            optional = prefix + "_overwritten"
        elif kind == "Update":
            required.update((prefix + "_move_present", prefix + "_old_hex", prefix + "_new_hex"))
            require(values[prefix + "_move_present"] in {"true", "false"}, "invalid move flag")
            if values[prefix + "_move_present"] == "true":
                required.update((prefix + "_move_debug_hex", prefix + "_move_native_hex"))
            optional = prefix + "_overwritten_move"
        else:
            require(kind == "Delete", "unknown delta variant")
            continue
        required.add(optional + "_present")
        require(values[optional + "_present"] in {"true", "false"}, "invalid overwritten flag")
        if values[optional + "_present"] == "true":
            required.add(optional + "_hex")
    for i in range(number(values["native_calls"])):
        required.update("native_" + str(i) + suffix for suffix in ("_request_hex", "_response_hex", "_status"))
    require(set(values) == required, "missing or unexpected application observation fields")
    if case["case"] == "unsupported_heredoc_unicode":
        require(case["entry"] in (0, 1) and values["status"] == "error"
                and values["kind"] == "ParseError" and values["delta_exact"] == "true"
                and number(values["delta_changes"]) == number(values["fs_events"]) == 0
                and not unhex(values["stdout_hex"]),
                "unsupported heredoc delimiter was not rejected before filesystem effects")


def writer_events(values):
    pending = {}
    counts = {(stream, kind): 0 for stream in ("stdout", "stderr")
              for kind in ("write", "format", "flush")}
    accepted = {stream: bytearray() for stream in ("stdout", "stderr")}
    errors = []
    for i in range(number(values["writer_events"])):
        event = effects.event_record(unhex(values[f"writer_event_{i}_hex"]).decode())
        stream, kind = event["stream"], event["kind"]
        require(stream in accepted and number(event["ordinal"]) == i, "writer order/stream differs")
        require(number(event["fs_events"]) == number(values["fs_events"]),
                "a diagnostic/summary write preceded completion of actual filesystem callbacks")
        if kind == "flush":
            require(event["result"] == "ok", "unexpected flush contract")
            counts[stream, "flush"] += 1
            continue
        category, phase = kind.rsplit("_", 1)
        require(category in {"write", "format"}, "unknown writer operation")
        call = number(event["call"])
        key = stream, category, call
        if phase == "begin":
            counts[stream, category] += 1
            require(call == counts[stream, category] and key not in pending, "writer call order differs")
            pending[key] = event
        else:
            require(phase == "end" and key in pending, "unpaired writer completion")
            begin = pending.pop(key)
            require(event["result"] in {"ok", "error"}, "unknown writer result")
            if event["result"] == "error":
                errors.append({"stream": stream, "kind": category, "error_kind": event["error_kind"]})
            elif category == "write":
                n = number(unhex(event["value_hex"]).decode())
                source = unhex(begin["input_hex"])
                require(n <= len(source), "writer accepted beyond its supplied bytes")
                accepted[stream].extend(source[:n])
    require(not pending, "a writer call did not complete")
    for stream in accepted:
        require(accepted[stream] == unhex(values[stream + "_hex"]), "accepted output prefix differs")
        for kind, suffix in (("write", "writes"), ("format", "formats"), ("flush", "flushes")):
            require(counts[stream, kind] == number(values[stream + "_" + suffix]), "writer count differs")
    return errors


def native_trace(values, entry, native, contract):
    count = number(values["native_calls"])
    require((count > 0) == native, "actual public application did not use its intended owner")
    allowed = {(t["entry"], t["phase"], t["event"]): (t["next_phase"], t["action"])
               for t in contract["transitions"]}
    previous, actions, transitions = 0, [], []
    for i in range(count):
        require(number(values[f"native_{i}_status"]) == 0, "actual application transport failed")
        request = struct.unpack("<8Q", unhex(values[f"native_{i}_request_hex"]))
        response = struct.unpack("<8Q", unhex(values[f"native_{i}_response_hex"]))
        require(request[0] == 1 and request[4:] == (0, 0, 0, 0), "actual request layout differs")
        require(request[1] == int(entry == 2) and request[2] == previous,
                "actual application continuation did not retain the native-selected state")
        if i == 0:
            require(request[3] == 0, "actual application did not start once")
        selection = allowed.get(request[1:4])
        require(selection is not None, "actual application sent an invalid transition")
        next_phase, action = selection
        require(response == (1, request[1], next_phase, action, request[2], request[3], 0, 0),
                "actual native transition does not match the fixed transport contract")
        previous = next_phase
        actions.append(action)
        transitions.append(":".join(str(value) for value in request[1:4]))
    require(not native or previous == 8, "actual application did not reach a terminal value")
    return {"actions": actions, "transitions": transitions}


def public_bytes(raw):
    # Only the explicitly separate native-symbol trace is removed. No path,
    # error spelling, contents, filesystem result, or writer result is normalized.
    return b"\n".join(line for line in raw[:-1].split(b"\n")
        if not re.fullmatch(rb"native_calls|native_[0-9]+_(?:request_hex|response_hex|status)",
                            line.partition(b"=")[0])) + b"\n"
