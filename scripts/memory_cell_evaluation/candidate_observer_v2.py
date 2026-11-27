"""Observe actual candidate unittest execution and nested subprocess.run costs."""

import hashlib
import json
from pathlib import Path
import resource
import runpy
import subprocess
import sys
import time
import unittest


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bounded_process import save
    from ruff_judge import RecordedResult, test_ids

    request = json.loads(Path(sys.argv[1]).read_bytes())
    output = Path(request["evidence"])
    output.mkdir()
    suites, nested = [], []
    remaining = 4 * 1024 * 1024
    original_run = subprocess.run
    original_tests = unittest.TextTestRunner.run

    def observed_process(*args, **kwargs):
        nonlocal remaining
        if len(nested) >= 512:
            raise RuntimeError("nested process evidence budget exhausted")
        directory = output / f"nested-{len(nested):04d}"
        directory.mkdir()
        argv = args[0] if args else kwargs["args"]
        row = {
            "argv": list(map(str, argv)) if isinstance(argv, (list, tuple)) else argv,
            "cwd": str(kwargs.get("cwd", Path.cwd())),
            "returncode": None,
            "error": None,
        }
        save(directory / "request.json", row)
        nested.append(row)
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started, completed = time.monotonic(), None
        try:
            completed = original_run(*args, **kwargs)
            row["returncode"] = completed.returncode
            return completed
        except Exception as error:
            completed = error
            row["returncode"] = getattr(error, "returncode", None)
            row["error"] = repr(error)
            raise
        finally:
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            row.update(
                wall_seconds=time.monotonic() - started,
                observed_waited_cpu_delta=after.ru_utime
                + after.ru_stime
                - before.ru_utime
                - before.ru_stime,
                measurement_basis="serialized subprocess.run; attribution only, included in outer wait4 cost",
            )
            for name in ("stdout", "stderr"):
                data = getattr(completed, name, None)
                if data is None:
                    row[name] = {"captured": False, "bytes": None}
                    continue
                if isinstance(data, str):
                    data = data.encode()
                retained = data[: min(request["nested_output_bytes"], remaining)]
                remaining -= len(retained)
                (directory / name).write_bytes(retained)
                row[name] = {
                    "captured": True,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "retained_prefix_bytes": len(retained),
                    "truncated": len(retained) < len(data),
                }
            save(directory / "process.json", row)

    def observed_tests(runner, suite):
        discovered = list(test_ids(suite))
        runner.resultclass = RecordedResult
        result = original_tests(runner, suite)
        suites.append(
            {
                "discovered": discovered,
                "started": result.started,
                "completed": result.completed,
                "outcomes": result.outcomes,
                "tests_run": result.testsRun,
                "unittest_success": result.wasSuccessful(),
            }
        )
        return result

    subprocess.run = observed_process
    unittest.TextTestRunner.run = observed_tests
    sys.path.insert(0, str(Path(request["workspace"]) / request["module_directory"]))
    argv = request["selection"]
    error, code = None, 0
    try:
        if argv[1:3] == ["-m", "unittest"]:
            sys.argv = ["unittest", *argv[3:]]
            runpy.run_module("unittest", run_name="__main__")
        else:
            target = Path(request["workspace"]) / argv[1]
            sys.argv = [str(target)]
            runpy.run_path(str(target), run_name="__main__")
    except SystemExit as exit_value:
        code = (
            exit_value.code
            if isinstance(exit_value.code, int)
            else 0
            if exit_value.code is None
            else 1
        )
    except Exception as exception:
        error, code = repr(exception), 1
    finally:
        subprocess.run = original_run
        unittest.TextTestRunner.run = original_tests
        report = {
            key: [item for suite in suites for item in suite[key]]
            for key in ("discovered", "started", "completed", "outcomes")
        }
        report.update(
            tests_run=sum(suite["tests_run"] for suite in suites),
            unittest_success=bool(suites)
            and all(suite["unittest_success"] for suite in suites),
            runner_exit=code,
            error=error,
            suite_invocations=len(suites),
            nested_processes=nested,
        )
        save(output / "semantic.json", report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
