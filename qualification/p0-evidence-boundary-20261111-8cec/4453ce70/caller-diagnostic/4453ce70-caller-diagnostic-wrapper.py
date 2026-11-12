import faulthandler
import runpy
import sys

faulthandler.enable()
faulthandler.dump_traceback_later(30, repeat=True)
sys.argv = ["scripts/verify_hepta_callers.py", "verify"]
try:
    runpy.run_path("scripts/verify_hepta_callers.py", run_name="__main__")
finally:
    faulthandler.cancel_dump_traceback_later()
