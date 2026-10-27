"""Exercise bounded control failure and label ownership with a tiny protocol fixture."""

import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest

from .commands import Commands
from .docker_control import DockerControl
from .files import describe, read_json


FAKE_DOCKER = """import json,pathlib,sys
root=pathlib.Path(sys.argv[0]).parent
args=sys.argv[1:]
state=json.loads((root/'state.json').read_text())
with (root/'actions.jsonl').open('a') as output: output.write(json.dumps(args)+'\\n')
if args[0]=='ps':
    if state['exists']: print(state['name'])
elif args[:2]==['container','inspect']:
    print(json.dumps([{'Config':{'Labels':{'hepta.linux.qualification':state['owner']}}}]))
elif args[0]=='logs': print('actual control fixture log; no Docker server exists')
elif args[0]=='stop': print(args[-1])
elif args[0]=='rm':
    state['exists']=False
    (root/'state.json').write_text(json.dumps(state))
elif args[0] in ('network','volume') and args[1]=='ls': pass
else: raise SystemExit('Unexpected fixture command: '+repr(args))
"""


class TeardownEvidence(unittest.TestCase):
    def test_interrupted_create_is_discovered_but_foreign_identity_is_never_removed(
        self,
    ):
        for scenario in ("owned", "foreign_name", "foreign_label"):
            with (
                self.subTest(scenario=scenario),
                tempfile.TemporaryDirectory(prefix="hepta-owned-control-") as temporary,
            ):
                root = Path(temporary).resolve()
                executable = root / "docker-protocol-fixture"
                executable.write_text(
                    "#!" + str(Path(sys.executable).resolve()) + "\n" + FAKE_DOCKER
                )
                executable.chmod(0o700)
                endpoint = socket.socket(socket.AF_UNIX)
                try:
                    endpoint.bind(str(root / "docker.sock"))
                    commands = Commands(
                        root / "commands",
                        {"docker": {"path": str(executable), **describe(executable)}},
                        {"DOCKER_HOST": "unix://" + str(root / "docker.sock")},
                        root,
                    )
                    control = DockerControl(commands, root, {}, root / "docker.sock")
                    owner = read_json(root / "RESOURCE_OWNER.json")
                    self.assertEqual(owner["prefix"], control.prefix)
                    name = control.prefix + "-interrupted-create"
                    state = {"name": name, "owner": control.prefix, "exists": True}
                    if scenario == "foreign_name":
                        state["name"] = "somebody-elses-container"
                    elif scenario == "foreign_label":
                        state["owner"] = "somebody-elses-label"
                    (root / "state.json").write_text(json.dumps(state))
                    # No in-memory resource append: emulate loss between the
                    # Docker create side effect and its successful return.
                    self.assertEqual(control.containers, [])
                    result = control.cleanup()
                    actions = [
                        json.loads(line)
                        for line in (root / "actions.jsonl").read_text().splitlines()
                    ]
                    removals = [args for args in actions if args[0] in {"stop", "rm"}]
                    if scenario == "owned":
                        self.assertTrue(result["all_owned_resources_absent"])
                        self.assertFalse(read_json(root / "state.json")["exists"])
                        self.assertEqual(
                            removals, [["stop", "--time", "30", name], ["rm", name]]
                        )
                    else:
                        self.assertFalse(result["all_owned_resources_absent"])
                        self.assertEqual(removals, [])
                        self.assertTrue(read_json(root / "state.json")["exists"])
                finally:
                    endpoint.close()

    def test_timed_out_control_command_keeps_a_failure_receipt(self):
        with tempfile.TemporaryDirectory(prefix="hepta-control-timeout-") as temporary:
            root = Path(temporary).resolve()
            executable = Path(sys.executable).resolve()
            commands = Commands(
                root / "commands",
                {"python": {"path": str(executable), **describe(executable)}},
                {},
                root,
            )
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                commands.run(
                    "python",
                    [
                        "-I",
                        "-c",
                        "import time; print('bounded control fixture', flush=True); time.sleep(2)",
                    ],
                    label="bounded-control",
                    timeout_seconds=0.2,
                )
            record = read_json(root / "commands/000-END.json")
            self.assertTrue(record["timeout_expired"])
            self.assertIsNone(record["exit_code"])
            self.assertTrue(record["executable_unchanged"])
            self.assertEqual(
                describe(root / "commands" / record["stdout"]["path"]),
                {key: record["stdout"][key] for key in ("bytes", "sha256")},
            )


if __name__ == "__main__":
    unittest.main()
