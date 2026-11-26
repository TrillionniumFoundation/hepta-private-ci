"""Real Linux process-transport fixtures; no human or Hepta qualification."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import native_adapter as adapter

FIXTURE = r"""
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
static void emit(int fd, size_t n) {
    char b[4096]; memset(b, 'x', sizeof b);
    while (n) { ssize_t k=write(fd,b,n<sizeof b?n:sizeof b);
        if(k<=0) _exit(4); n-=(size_t)k; }
}
int main(int argc, char **argv) {
    alarm(5);
    if(argc>1 && !strcmp(argv[1],"--help")) {
        puts("SYNTHETIC statement fixture: ORIGINAL_TURN_VERIFIER_REQUIRED --print-statement");
        return 0;
    }
    char in[256]={0}; if(read(0,in,sizeof in-1)<0) return 3;
    if(strstr(in,"fork")) {
        pid_t child=fork(); if(child<0) return 3;
        if(child==0) { alarm(5); for(;;) pause(); }
        char path[4096]; ssize_t n=readlink("/proc/self/exe",path,sizeof path-8);
        if(n<0) return 3; path[n]=0; strcat(path,".pid");
        FILE *f=fopen(path,"w"); if(!f) return 3;
        fprintf(f,"%ld\n",(long)child); fclose(f);
        if(strstr(in,"exit")) return 0;
    }
    if(strstr(in,"timeout")) for(;;) pause();
    if(strstr(in,"stderr")) emit(2,32769);
    else if(strstr(in,"over")) emit(1,32769);
    else { emit(1,32768); emit(2,32768); }
    return 0;
}
"""

@unittest.skipUnless(sys.platform == "linux" and shutil.which("cc"), "Linux C fixture required")
class NativeStatementProcesses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.folder.name) / "statement-fixture"
        source = cls.binary.with_suffix(".c")
        source.write_text(FIXTURE)
        subprocess.run(["cc", "-O0", str(source), "-o", str(cls.binary)],
                       check=True, timeout=30)
        cls.binary.chmod(0o700)
        cls.pin = hashlib.sha256(cls.binary.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def call(self, mode, timeout=2):
        return adapter.invoke(self.binary, self.pin, {"case": mode}, timeout)

    def test_exact_both_stream_limits(self):
        self.assertEqual(self.call("exact"), b"x" * adapter.MAX_OUTPUT)

    def test_each_output_limit_rejects_real_bytes(self):
        for mode in ("stdout_over", "stderr_over"):
            with self.subTest(mode=mode), self.assertRaisesRegex(adapter.Refused, "output bound"):
                self.call(mode)

    def test_group_stops_on_overflow_timeout_and_leader_exit(self):
        for mode in ("fork_over", "fork_timeout", "fork_exit"):
            with self.subTest(mode=mode):
                marker = Path(str(self.binary) + ".pid")
                marker.unlink(missing_ok=True)
                with self.assertRaises(adapter.Refused):
                    self.call(mode, timeout=0.3)
                child = int(marker.read_text())
                deadline = time.monotonic() + 1
                while True:
                    try:
                        state = Path(f"/proc/{child}/stat").read_text().rsplit(") ", 1)[1][0]
                    except FileNotFoundError:
                        break
                    if state in ("Z", "X"):
                        break  # No live group member; external reaping is not asserted.
                    self.assertLess(time.monotonic(), deadline, "fixture descendant is still live")
                    time.sleep(0.01)

    def test_pin_and_authority_refusals_survive(self):
        with self.assertRaisesRegex(adapter.Refused, "ELF pin changed"):
            adapter.invoke(self.binary, "1" * 64)
        with self.assertRaisesRegex(adapter.Refused, adapter.BLOCKER):
            adapter.authorize_owner()
        status = adapter.authorization_status(self.binary, self.pin)
        self.assertFalse(status["original_turn_authorization_available"])


if __name__ == "__main__":
    unittest.main()
