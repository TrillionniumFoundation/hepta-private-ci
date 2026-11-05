"""Replay the null-transfer liveness defect on a disposable authority only.

Pass a checkout's qualification/memory-cell-v15 directory as the sole argument.
The same probe records both the original accepted/frozen state and repaired
rejection followed by a successful ordinary handoff. No production DB is read.
"""
import hashlib
import json
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source))
from authority import Rejected, public
from authority_tests import AuthorityTests, key

fixture = AuthorityTests("test_signed_receipt_and_tampered_command")
fixture.setUp()


def invoke(operation, args, actor=3):
    try:
        return {"accepted": True, "result": fixture.call(operation, args, actor)}
    except Rejected as exc:
        return {"accepted": False, "reason": str(exc)}


try:
    identifier = fixture.item["id"]
    report = {"authority_sha256": hashlib.sha256((source / "authority.py").read_bytes()).hexdigest(),
              "probe_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
              "scope": "Disposable signed SQLite fixture; no model quality or production claim."}
    report["null_prepare"] = invoke("prepare", dict(cell="cell", epoch=1, expected=identifier,
                                                   transfer=None, target=public(key(4))))
    if report["null_prepare"]["accepted"]:
        args = dict(cell="cell", epoch=2, expected=identifier, transfer=None)
        report["owner_abort"] = invoke("abort", args)
        report["admin_abort"] = invoke("abort", args, 2)
        report["receiver_ready"] = invoke("ready", dict(args, bundle=fixture.item), 4)
        report["receiver_commit"] = invoke("commit", args, 4)
        report["admin_recovery"] = invoke("recover_prepare", dict(args, transfer="recovery",
                                                                  target=public(key(5))), 2)
    else:
        report["next_prepare"] = invoke("prepare", dict(cell="cell", epoch=1, expected=identifier,
                                                        transfer="valid", target=public(key(4))))
        args = dict(cell="cell", epoch=2, expected=identifier, transfer="valid")
        report["next_ready"] = invoke("ready", dict(args, bundle=fixture.item), 4)
        report["next_commit"] = invoke("commit", args, 4)
    report["final_state"] = fixture.call("status", {"cell": "cell"}, 2)
    print(json.dumps(report, indent=2, ensure_ascii=True))
finally:
    fixture.tearDown()
