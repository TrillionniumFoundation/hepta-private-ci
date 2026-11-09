"""Local process client for the actual Rust fast-memory kernel."""

import hashlib
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time


class NativeMemory:
    def __init__(self, binary, state, generation, width=16, outputs=8, eta=0.5):
        self.binary = str(Path(binary).resolve())
        self.state, self.generation = state, generation
        self.width, self.outputs, self.eta = width, outputs, eta
        self.stderr = tempfile.TemporaryFile(mode="w+t")
        self.process = subprocess.Popen(
            [self.binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            bufsize=1,
        )
        self.replies = queue.Queue()
        self.reader = threading.Thread(target=self.read_replies, daemon=True)
        self.reader.start()
        self.multiplications = self.calls = self.wall_ns = 0
        try:
            reply = self.command(
                f"new {state} scope:mem1 {generation} {width} {outputs} {eta} 1"
            )
            self.digest, self.state_bytes = reply[1], int(reply[2])
        except Exception:
            self.close()
            raise

    def read_replies(self):
        for line in self.process.stdout:
            self.replies.put(line)
        self.replies.put("")

    def command(self, text):
        start = time.perf_counter_ns()
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()
        try:
            line = self.replies.get(timeout=10)
        except queue.Empty as error:
            raise TimeoutError(
                "native protocol response exceeded 10 seconds"
            ) from error
        self.wall_ns += time.perf_counter_ns() - start
        self.calls += 1
        if not line:
            self.stderr.seek(0)
            raise RuntimeError("native driver exited: " + self.stderr.read(4096))
        reply = line.strip().split("\t")
        if reply[0] == "ERR":
            raise ValueError(line.strip())
        return reply

    def predict(self, key):
        result = self.command(f"predict {self.generation} " + ",".join(map(repr, key)))
        self.digest = result[1]
        self.multiplications += int(result[2])
        return [float(value) for value in result[3].split(",")]

    def update(self, key, target, support):
        result = self.command(
            f"update {self.generation} {support} "
            + ",".join(map(repr, key))
            + " "
            + ",".join(map(repr, target))
        )
        self.digest = result[1]
        self.multiplications += int(result[2])
        return {"sequence": int(result[3]), "loss": float(result[4])}

    def checkpoint(self):
        result = self.command("checkpoint")
        if hashlib.sha256(bytes.fromhex(result[2])).hexdigest() != result[1]:
            raise ValueError("native checkpoint hash mismatch")
        return result[1], result[2]

    def restore(self, checkpoint):
        result = self.command("restore " + " ".join(checkpoint))
        self.digest = result[1]

    def reset(self, generation, suffix):
        state = f"{self.state}:{suffix}"
        result = self.command(f"reset {state} {generation}")
        self.state, self.generation, self.digest = state, generation, result[1]

    def clone(self):
        checkpoint = self.checkpoint()
        result = NativeMemory(
            self.binary, self.state, self.generation, self.width, self.outputs, self.eta
        )
        result.restore(checkpoint)
        return result

    def restart(self, directory):
        """Persist bytes and a separate owner witness, exit, then restore a new PID."""
        checkpoint = self.checkpoint()
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        (path / "state.bin").write_bytes(bytes.fromhex(checkpoint[1]))
        (path / "owner-witness.txt").write_text(checkpoint[0] + "\n")
        old_pid = self.process.pid
        self.close()
        restored = NativeMemory(
            self.binary, self.state, self.generation, self.width, self.outputs, self.eta
        )
        restored.restore(
            (
                (path / "owner-witness.txt").read_text().strip(),
                (path / "state.bin").read_bytes().hex(),
            )
        )
        if restored.process.pid == old_pid or restored.digest != checkpoint[0]:
            raise ValueError(
                "restart did not restore the independently witnessed state"
            )
        return restored

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write("quit\n")
                self.process.stdin.flush()
                self.process.wait(timeout=2)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                # Only this client-created worker; never a build or shared job.
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
        self.reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.stderr):
            stream.close()


def argmax(values):
    return max(range(len(values)), key=values.__getitem__)
