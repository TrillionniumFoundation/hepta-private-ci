"""Author checks for cancellation and pre-world CPU gates; synthetic fixtures only."""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import resource
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.hcsn.digital_feedback_20261101 import freeze, study


class ControlGates(unittest.TestCase):
    expected_rejections = []

    def test_stop_before_first_spawn_records_zero_child_cost(self):
        with tempfile.TemporaryDirectory(prefix="digital-stop-fixture-") as directory:
            root = Path(directory)/"new_run"
            args = SimpleNamespace(root=root,stage="train",protocol=Path(directory)/"protocol.json",
                                   workers=2,training=None,seal=None)
            protocol = dict(fits=[1,2,3])
            original_write = study.write

            def stop_after_launch(path,value):
                result = original_write(path,value)
                if Path(path).name == "LAUNCH.json":
                    original_write(root/"STOP_AFTER_ACTIVE.json",dict(reason="synthetic fixture"))
                return result

            with patch.object(study,"sources",return_value={}), patch.object(study,"write",side_effect=stop_after_launch):
                with patch.object(study.subprocess,"Popen",side_effect=AssertionError("cancelled worker spawned")) as spawn:
                    with redirect_stdout(io.StringIO()):
                        study.launch(args,protocol)
            spawn.assert_not_called()
            for fit in protocol["fits"]:
                record = study.read(root/"process_receipts"/f"fit_{fit}.json")
                self.assertEqual([record[k] for k in ("spawned","cancelled","returncode","cpu_seconds")],
                                 [False,True,None,0.])
                self.assertTrue((root/f"fit_{fit}"/"CANCELLED_BEFORE_START.json").exists())
                self.assertFalse((root/f"fit_{fit}"/"STARTED.json").exists())
                self.assertFalse((root/f"fit_{fit}"/"FAILED.json").exists())
            controller = study.read(root/"CONTROLLER_RECEIPT.json")
            self.assertEqual(controller["spawned_fits"],[])
            self.assertEqual(controller["cancelled_before_start_fits"],protocol["fits"])
            self.assertEqual(controller["status"],"stopped_after_active")

    def test_active_worker_finishes_without_spawning_the_pending_fits(self):
        with tempfile.TemporaryDirectory(prefix="digital-drain-fixture-") as directory:
            root = Path(directory)/"new_run"
            args = SimpleNamespace(root=root,stage="train",protocol=Path(directory)/"protocol.json",
                                   workers=3,training=None,seal=None)
            handles = []

            def spawn(command,**kwargs):
                handles.extend((kwargs["stdout"],kwargs["stderr"]))
                study.write(root/"STOP_AFTER_ACTIVE.json",dict(reason="after one synthetic worker"))
                return SimpleNamespace(pid=12345,returncode=None)

            usage = SimpleNamespace(ru_utime=100.,ru_stime=20.,ru_maxrss=128)
            with patch.object(study,"sources",return_value={}), patch.object(study.subprocess,"Popen",side_effect=spawn) as spawned:
                with patch.object(study.os,"wait4",return_value=(12345,0,usage)) as waited:
                    with redirect_stdout(io.StringIO()):
                        study.launch(args,dict(fits=[1,2,3]))
            self.assertEqual(spawned.call_count,1)
            waited.assert_called_once_with(12345,study.os.WNOHANG)
            self.assertTrue(all(handle.closed for handle in handles))
            receipt = study.read(root/"process_receipts/fit_1.json")
            self.assertEqual([receipt[k] for k in ("spawned","cancelled","returncode","cpu_seconds")],
                             [True,False,0,120.])
            controller = study.read(root/"CONTROLLER_RECEIPT.json")
            self.assertEqual(controller["spawned_fits"],[1])
            self.assertEqual(controller["completed_fits"],[1])
            self.assertEqual(controller["cancelled_before_start_fits"],[2,3])
            self.assertEqual(controller["active_pids"],[])
            self.assertLess(controller["controller_launch_cpu_seconds"],1.)
            self.assertLess(controller["controller_self_cpu_seconds"],120.)

    def test_failed_cpu_contract_blocks_seal_and_confirmation_before_worlds(self):
        bad_costs = [None,{},dict(all_actual_cpu_matching=False,all_training_valid=True),
                     dict(all_actual_cpu_matching=True,all_training_valid=False),
                     dict(all_actual_cpu_matching=1,all_training_valid=1)]
        with tempfile.TemporaryDirectory(prefix="digital-cpu-gate-fixture-") as directory:
            base = Path(directory)
            for index,cost in enumerate(bad_costs):
                manifest = base/f"manifest_{index}.json"
                study.write(manifest,dict(cpu_matching=cost))
                output = base/f"seal_{index}.json"
                argv = ["freeze","seal","--manifest",str(manifest),"--output",str(output)]
                with self.subTest(index=index),patch.object(sys,"argv",argv):
                    with self.assertRaisesRegex(ValueError,"confirmation requires"):
                        freeze.main()
                self.assertFalse(output.exists())
                future = base/f"future_confirmation_{index}"
                with patch.object(study,"sources",side_effect=AssertionError("source loading preceded CPU gate")) as source:
                    with patch.object(study,"cohort",side_effect=AssertionError("future worlds generated")) as worlds:
                        with self.assertRaisesRegex(ValueError,"confirmation requires"):
                            study.confirm(future,base/"unused_training",manifest,1,{},base/"unused_protocol")
                source.assert_not_called()
                worlds.assert_not_called()
                self.assertFalse(future.exists())
                self.expected_rejections.append(dict(case=index,cpu_matching=cost,seal_rejected=True,
                                                     confirmation_rejected=True,worlds_generated=False))
            study.require_confirmation_qualification(dict(cpu_matching=dict(
                all_actual_cpu_matching=True,all_training_valid=True)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    start = time.process_time()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ControlGates))
    root = Path(__file__).resolve().parents[1]
    usage = resource.getrusage(resource.RUSAGE_SELF)
    report = dict(schema="digital-feedback-control-gate-checks-v1",tests_run=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),passed=result.wasSuccessful(),
        expected_rejections=ControlGates.expected_rejections,synthetic_fixtures_only=True,
        actual_workers_spawned=0,worlds_generated=False,
        source_sha256={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (root/"study.py",root/"freeze.py")},
        test_cpu_seconds=time.process_time()-start,process_cpu_to_report_seconds=usage.ru_utime+usage.ru_stime)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps(report,sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)
