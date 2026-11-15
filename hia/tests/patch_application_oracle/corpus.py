"""Fixed natural filesystem inputs and actual in-memory writer contracts."""
import itertools
import json
import struct

NAMES = (
    "add_new", "add_overwrite", "add_nested", "add_invalid_utf8",
    "add_directory", "add_symlink", "delete_existing", "delete_missing",
    "delete_directory", "delete_invalid_utf8", "delete_symlink", "update_existing",
    "update_crlf", "update_missing", "update_directory", "update_invalid_utf8",
    "update_symlink", "move_new", "move_overwrite", "move_nested",
    "move_target_directory", "move_same_path", "move_dot_alias", "move_source_symlink",
    "move_destination_symlink", "prefix_then_delete_missing", "prefix_then_update_missing",
    "mixed_success", "empty_patch", "invalid_patch", "invalid_hunk",
    "invalid_after_valid_hunk", "invalid_unicode", "unchanged_update",
    "mismatched_update", "prefix_then_mismatch", "unicode_add", "unicode_move",
    "mixed_line_endings", "nul_path", "prefix_then_nul_path", "heredoc_unicode",
    "large_content",
)
INVALID = frozenset(("invalid_patch", "invalid_hunk", "invalid_after_valid_hunk",
                     "invalid_unicode"))
MANUAL = ("manual_nonutf8_path", "manual_embedded_lines", "manual_empty")
CONTEXTS = {
    "none": "",
    "present_disabled": json.dumps({"permissions": {"type": "disabled"},
        "windowsSandboxLevel": "disabled"}, separators=(",", ":")),
    "present_restricted_unconfigured": json.dumps({"permissions": {
        "type": "managed", "file_system": {"type": "restricted", "entries": []},
        "network": "restricted"}, "windowsSandboxLevel": "disabled"},
        separators=(",", ":")),
}
UNLIMITED = (0, 0, 0, 1 << 24)
FORMATTING = (1, 0, 0, 1 << 24)


def matrix():
    cases = []

    def add(name, entry, mode=0, follow=1, context="none", profile="normal",
            stdout=UNLIMITED, stderr=UNLIMITED):
        cases.append({"id": len(cases), "case": name, "entry": entry, "mode": mode,
            "follow_symlinks": follow, "context": context, "sandbox_json": CONTEXTS[context],
            "writer_profile": profile, "stdout_policy": stdout, "stderr_policy": stderr})

    for name, mode, follow, context in itertools.product(NAMES, (0, 1), (0, 1), CONTEXTS):
        add(name, 0, mode, follow, context)
    for name, context in itertools.product(NAMES, CONTEXTS):
        add(name, 1, context=context)
    for name, context in itertools.product(tuple(n for n in NAMES if n not in INVALID) + MANUAL,
                                            CONTEXTS):
        add(name, 2, context=context)
    profiles = {
        "short": ((0, 0, 0, 1), (0, 0, 0, 1)),
        "format_observer": (FORMATTING, FORMATTING),
        "stdout_error_first": ((0, 1, 1, 1 << 24), UNLIMITED),
        "stdout_error_second": ((0, 1, 2, 1 << 24), UNLIMITED),
        "stdout_zero": ((0, 2, 0, 1 << 24), UNLIMITED),
        "stdout_prefix": ((0, 2, 7, 1 << 24), UNLIMITED),
        "stderr_error_first": (UNLIMITED, (0, 1, 1, 1 << 24)),
        "stderr_error_second": (UNLIMITED, (0, 1, 2, 1 << 24)),
        "stderr_zero": (UNLIMITED, (0, 2, 0, 1 << 24)),
        "stderr_prefix": (UNLIMITED, (0, 2, 7, 1 << 24)),
        "both_error_first": ((0, 1, 1, 1 << 24), (0, 1, 1, 1 << 24)),
        "write_interrupted_once": ((0, 3, 1, 1 << 24), (0, 3, 1, 1 << 24)),
        "stdout_format_error": ((1, 4, 1, 1 << 24), FORMATTING),
        "stdout_second_format_error": ((1, 4, 2, 1 << 24), FORMATTING),
        "stderr_format_error": (FORMATTING, (1, 4, 1, 1 << 24)),
        "stderr_format_interrupted": (FORMATTING, (1, 5, 1, 1 << 24)),
        "both_format_error": ((1, 4, 1, 1 << 24), (1, 4, 1, 1 << 24)),
    }
    targets = sorted(INVALID) + ["delete_missing", "mismatched_update",
        "prefix_then_delete_missing", "prefix_then_mismatch", "empty_patch",
        "prefix_then_nul_path", "add_overwrite", "mixed_success", "unicode_move",
        "unchanged_update", "unicode_add"]
    for name in targets:
        for entry in ((0, 1) if name in INVALID else (0, 1, 2)):
            for profile, (stdout, stderr) in profiles.items():
                add(name, entry, profile=profile, stdout=stdout, stderr=stderr)
    return cases


def wire(case):
    words = (case["entry"], case["mode"], case["follow_symlinks"],
             *case["stdout_policy"], *case["stderr_policy"])
    result = b"HPAO0001" + struct.pack("<11Q", *words)
    for name in ("case", "sandbox_json"):
        value = case[name].encode()
        result += struct.pack("<Q", len(value)) + value
    return result


def decode(data):
    if data[:8] != b"HPAO0001" or len(data) < 112:
        raise ValueError("invalid application observer wire header")
    words = struct.unpack_from("<11Q", data, 8)
    entry, mode, follow = words[:3]
    if entry > 2 or mode > 1 or follow > 1 or (entry and (mode != 0 or follow != 1)):
        raise ValueError("invalid entry/options")
    for style, policy, point, fragment in (words[3:7], words[7:11]):
        if style > 1 or policy > 5 or fragment == 0 or (style == 0 and policy >= 4):
            raise ValueError("invalid writer policy")
    offset, values = 96, []
    for _ in range(2):
        if offset + 8 > len(data):
            raise ValueError("truncated observer string header")
        length, = struct.unpack_from("<Q", data, offset)
        offset += 8
        if length > len(data) - offset:
            raise ValueError("truncated observer string")
        values.append(data[offset:offset + length].decode("utf-8"))
        offset += length
    if offset != len(data) or values[0] not in NAMES + MANUAL:
        raise ValueError("unknown fixture or trailing bytes")
    if values[0] in MANUAL and entry != 2:
        raise ValueError("typed-only fixture requires direct entry")
    return {"entry": entry, "mode": mode, "follow_symlinks": follow,
            "stdout_policy": words[3:7], "stderr_policy": words[7:11],
            "case": values[0], "sandbox_json": values[1]}
