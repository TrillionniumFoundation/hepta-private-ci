"""Validate the three memory-only parent checks without changing the native verdict."""

import re

from environment_observer_parser import ANSI, integer, keys, records, require

MARKER = "HEPTA_PARENT_DELETE_CHILD"
ORIGINAL_MARKER = "HEPTA_PRODUCTION_DELETE"
VARIANTS = ("original_copy", "workspace_capability_deny", "actual_user_deny")
SUMMARY_GATES = (
    "captured_token_facts_equal", "descriptor_copies_unchanged", "source_memory_unchanged",
    "original_copy_byte_equal", "positive_and_identity_controls_match",
    "access_results_consistent", "non_dacl_components_and_original_aces_preserved",
)


def verify_parent_sd(texts):
    row, = records(texts, MARKER, 4096, 1)
    keys(row, "kind phase requested descriptor_source rows summary")
    require(row["kind"] == "parent_delete_child_memory"
            and row["phase"] == "before_original_outside_actions"
            and row["descriptor_source"] == "pre_action_memory", "parent-SD provenance mismatch")
    integer(row["requested"], 64, 64)
    variants = row["rows"]
    require(type(variants) is list and len(variants) == 3, "parent-SD query count changed")
    for entry, name in zip(variants, VARIANTS):
        keys(entry, "variant result")
        require(entry["variant"] == name, "parent-SD variant order changed")
        result = entry["result"]
        keys(result, "api_success allowed granted win32_error privilege_count")
        require(result["api_success"] is True and type(result["allowed"]) is bool,
                "parent-SD AccessCheck API result is unknown")
        integer(result["granted"], 0, 64)
        require(result["granted"] == (64 if result["allowed"] else 0),
                "parent-SD granted access contradicts allowed")
        integer(result["privilege_count"], 0, 256)
        if result["allowed"]:
            require(result["win32_error"] is None, "successful parent-SD access has an error")
        else:
            integer(result["win32_error"])
    require(variants[0]["result"]["allowed"] is True
            and variants[2]["result"]["allowed"] is False, "parent-SD controls did not match")

    summary = row["summary"]
    keys(summary, "status " + " ".join(SUMMARY_GATES)
         + " selected_capability_index selected_capability_is_restricting_only"
         + " selected_restricting_attributes restricting_count parent_sd_bytes")
    require(summary["status"] == "observed", "parent-SD summary is unknown")
    require(all(summary[name] is True for name in SUMMARY_GATES),
            "parent-SD memory, token or control invariant was not established")
    integer(summary["selected_capability_index"], 0, 0)
    require(summary["selected_capability_is_restricting_only"] is True,
            "parent-SD selected capability also has ordinary authority")
    integer(summary["selected_restricting_attributes"])
    integer(summary["restricting_count"], 2, 2)
    # The Rust reader requires a 20-byte relative header and at least one
    # complete eight-byte component starting at or beyond that header.
    integer(summary["parent_sd_bytes"], 28, 65536)

    # All original factory records and the new record come from the same captured
    # stderr stream. Do not invent an order by concatenating stdout and stderr.
    streams = []
    for text in texts:
        before_summary = re.split(r"(?m)^\s*Summary\s+\[", ANSI.sub("", text), maxsplit=1)[0]
        sequence = []
        for line in before_summary.splitlines():
            if MARKER in line:
                sequence.append(MARKER)
            elif ORIGINAL_MARKER in line:
                sequence.append(ORIGINAL_MARKER)
        if sequence:
            streams.append(sequence)
    require(streams == [[ORIGINAL_MARKER] * 7 + [MARKER] + [ORIGINAL_MARKER] * 8],
            "parent-SD record is not between the original before and after observations")
    original = records(texts, ORIGINAL_MARKER, 16 * 1024, 15)
    token, parent = original[0], original[2]
    require(type(token) is dict and token.get("kind") == "token" and token.get("phase") == "before"
            and token.get("exact_expected_capabilities") is True
            and token.get("sd_memory_unchanged") is True,
            "parent-SD original token anchor is unavailable")
    integer(token.get("token_type"), 2, 2)
    integer(token.get("restricting_count"), 2, 2)
    require(type(parent) is dict and parent.get("kind") == "access" and parent.get("phase") == "before"
            and parent.get("object") == "parent"
            and parent.get("descriptor_source") == "pre_action_memory",
            "parent-SD original access anchor is unavailable")
    integer(parent.get("requested"), 64, 64)
    anchor = parent.get("result")
    require(type(anchor) is dict and anchor.get("api_success") is True
            and anchor.get("allowed") is True, "parent-SD baseline contradicts the original query")
    integer(anchor.get("granted"), 64, 64)
    # The old verifier owns the complete 15-record contract. Redacted summaries
    # cannot independently reconstruct raw SID or descriptor equality.
    return row


def record_parent_sd_observation(report, texts):
    result = {"record_complete": False, "status": "unknown",
              "production_confinement_qualified": False}
    report["native"]["parent_sd_observation"] = result
    try:
        row = verify_parent_sd(texts)
        result.update({"record_complete": True, "status": "observed", "record": row,
                       "capability_deny_blocks_this_access_check": not row["rows"][1]["result"]["allowed"]})
    except Exception as error:
        report["errors"].append(f"parent-SD-observation: {type(error).__name__}: {error}")
