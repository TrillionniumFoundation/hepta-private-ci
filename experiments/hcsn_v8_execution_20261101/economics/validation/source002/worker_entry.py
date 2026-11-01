"""Report the identity of the owned spawn before replacing it with the task."""

import json
import os
import sys

from experiments.hcsn_v7_support_20261101.memory_observer.process_memory import Observer, Unavailable


def main():
    command = sys.argv[1:]
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("A task command is required")
    try:
        identity = Observer().own_identity().record()
        message = {"kind": "owned_exec_identity", "identity": identity}
    except Unavailable as error:
        message = {"kind": "owned_exec_identity", "identity": None, "reason": str(error)}
    print(json.dumps(message), flush=True)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
