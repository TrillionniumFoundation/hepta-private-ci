"""Exact historical workflow observations, preserved without live-workflow claims."""

import hashlib


# These bytes were retained at 6492f72ffbd3d7c477406fbabfc41e09f429324c.
# They record old run identities and commit comparisons, including failures.
# Only these original records may refer to retired workflow paths. Neighboring
# files, new observations and changed bytes still require ordinary validation.
FROZEN_WORKFLOW_HISTORY = {
    "qualification/hcsn_sustained_20261128/audit/source_and_tag_evidence.json": (
        "8574d49c06501095855008b156ad1fb0d08defd08dbccdef56a58090c1c96635"
    ),
    "qualification/continuation-20261021/environment/prior-worktree-observations.json": (
        "57ca9800d444693535d03e18b588f099158a8c127d77ec364e627e77b98b11b2"
    ),
    "qualification/continuation-20261021/environment/runtime-final.json": (
        "8698d822cf3c483d9df86c2ec80bf8441e36b5ec1baf9adbb37fb0000c2c9737"
    ),
    "qualification/continuation-20261021/inventory/compare/1500-1504.json": (
        "0c7a7be212587ccf638cbff085d1fe367fd681b9c47bb634b34fb76bbc63e954"
    ),
    "qualification/continuation-20261021/inventory/compare/1501-1504.json": (
        "6cca25bd763e77fd887e5eb6640d1225860f25154de079f2d272c55b90917164"
    ),
    "qualification/continuation-20261021/inventory/compare/1504-2937.json": (
        "bbe50f994f781579ae8591196b39ce211c7f3869fd4112959b1146e43f790779"
    ),
    "qualification/continuation-20261021/inventory/compare/2688-2937.json": (
        "92e2a32db484d2d8f59451d00a392337269213018a06f6a53305e86348c3f851"
    ),
    "qualification/continuation-20261021/inventory/compare/2695-2937.json": (
        "957c8d657be1ea3a804480e171f67d1a76018292c19f1b6dc167e3610f2fe617"
    ),
    "qualification/continuation-20261021/inventory/compare/2815-2937.json": (
        "69fe020c16957f35b8be32c60ff69873cceed538a36dea2049917e742c23e1ac"
    ),
    "qualification/continuation-20261021/inventory/compare/2879-2937.json": (
        "6999c33b708126de0523f8bb3a2efcd0e7eebcf9b7288a518c360aa76d3982aa"
    ),
    "qualification/continuation-20261021/inventory/compare/2883-2937.json": (
        "53305d4bd9766fc0eb9c3ea0d2283aef58df642cd71a91f80d3217aba431d45d"
    ),
    "qualification/continuation-20261021/inventory/compare/2924-2937.json": (
        "c6bd0630ed9fe377131285243ee59960e07c1eb913a9f63c88aedd3efb49c352"
    ),
    "qualification/continuation-20261021/inventory/compare/2937-2961.json": (
        "b81b73d672c156945edf97eeb646ab065da3e13f68549d4667d4f2fbc076c8fd"
    ),
    "qualification/continuation-20261021/research/archive_run.json": (
        "2c3b60df8a60175624c3cd757719b0cf3690977a938a12b6b4043109095d0106"
    ),
    "qualification/continuation-20261021/research/original_run.json": (
        "d13449a7f1242bf10632b3dca573ad3b63704cf70225a42d3832b502e693bc3c"
    ),
}


def is_frozen_workflow_history(relative_path, raw):
    expected = FROZEN_WORKFLOW_HISTORY.get(relative_path)
    if expected is None:
        return False
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"historical workflow observation changed: {relative_path}")
    return True
