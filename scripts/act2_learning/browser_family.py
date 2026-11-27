"""Actual headless browser/HTTP/filesystem fixture; never an open-web claim."""

import argparse
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import time

from file_family import FileOwner
from sqlite_destination import BudgetExhausted


class BrowserUnavailable(RuntimeError):
    pass


def decode_request(body, version):
    """The two versions have distinct wire schemas, both checked before dispatch."""
    if version == 1:
        if set(body) != {"key", "goal", "invocation", "version"}:
            raise ValueError("v1 request shape mismatch")
        result = body["key"], body["goal"], body["invocation"], body["version"]
    else:
        if set(body) != {"record", "operation", "codec"} or set(body["record"]) != {
            "id",
            "content",
        }:
            raise ValueError("v2 request shape mismatch")
        result = (
            body["record"]["id"],
            body["record"]["content"],
            body["operation"],
            body["codec"],
        )
    if type(result[0]) is not int or type(result[3]) is not int:
        raise ValueError("integer key and codec required")
    return result


def form_html(version):
    # Only the admitted codec is interpolated. Task strings enter via DOM fill.
    return (
        """<!doctype html><meta charset=utf-8><title>ACT controlled owner</title>
<label>Record<input id=key></label><label>Content<textarea id=goal></textarea></label>
<label>Invocation<input id=invocation></label>
<button id=inspect>Inspect</button><button id=stage>Stage</button><button id=apply>Apply</button>
<output id=result data-sequence=0></output><script>
const version=VERSION;
const out=document.querySelector('#result');
async function send(action) {
  const key=Number(document.querySelector('#key').value);
  const goal=document.querySelector('#goal').value;
  const invocation=document.querySelector('#invocation').value;
  const body=version===1 ? {key,goal,invocation,version} :
    {record:{id:key,content:goal},operation:invocation,codec:version};
  try {
    const r=await fetch('/v'+version+'/'+action, action==='inspect' ? {} :
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    out.textContent=JSON.stringify({http_status:r.status,body:await r.json()});
  } catch(e) { out.textContent=JSON.stringify({transport_error:true}); }
  out.dataset.sequence=String(Number(out.dataset.sequence)+1);
}
for (const action of ['inspect','stage','apply'])
  document.querySelector('#'+action).onclick=()=>send(action);
</script>"""
    ).replace("VERSION", str(version))


class BrowserDestination:
    """ACT2-compatible public interface, with every primitive driven through DOM."""

    def __init__(self, path, task, browser):
        self.started = time.perf_counter_ns()
        self.task, self.owner = task, FileOwner(Path(path), task)
        self.budget = 6 * len(task["goals"]) + 6
        self.calls = self.failed_reads = self.lost_replies = 0
        self.reads = self.writes = self.http_requests = self.network_requests = 0
        self.network_failures = self.dom_actions = self.browser_control_calls = 0
        self.view, self.last, self.events = None, "start", []
        self.context = self.server = self.thread = None
        self.closed, self.cleanup_ns = False, 0
        self.complete_ns = None
        destination = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, value, html=False):
                raw = value.encode() if html else json.dumps(value).encode()
                self.send_response(code)
                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8" if html else "application/json",
                )
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                destination.http_requests += 1
                if self.path == "/":
                    self.reply(200, form_html(task["version"]), True)
                elif self.path == f"/v{task['version']}/inspect":
                    try:
                        self.reply(200, destination.owner.observe())
                    except ValueError:
                        self.reply(500, {"error": "owner invariant failure"})
                else:
                    self.reply(404, {"error": "unknown route"})

            def do_POST(self):
                destination.http_requests += 1
                action = self.path.rsplit("/", 1)[-1]
                if self.path != f"/v{task['version']}/{action}" or action not in (
                    "stage",
                    "apply",
                ):
                    self.reply(404, {"error": "unknown route"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 65536:
                        raise ValueError("invalid body length")
                    key, goal, invocation, version = decode_request(
                        json.loads(self.rfile.read(length)), task["version"]
                    )
                    if action == "stage":
                        result = destination.owner.stage(key, goal, version)
                    else:
                        result = destination.owner.apply(key, goal, invocation, version)
                    if result.get("ack_lost"):
                        # Commit happened, but no applied bit is delivered to the actor.
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
                    self.reply(200, result)
                except (ValueError, TypeError, KeyError):
                    self.reply(400, {"error": "request rejected"})

        try:
            try:
                self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            except OSError as error:
                if error.errno in (
                    errno.EACCES,
                    errno.EPERM,
                    errno.EAFNOSUPPORT,
                    errno.ENOSYS,
                ):
                    raise BrowserUnavailable(
                        f"loopback owner server unavailable: {error}"
                    ) from error
                raise
            self.server.daemon_threads = True
            self.thread = threading.Thread(
                target=lambda: self.server.serve_forever(poll_interval=0.02),
                daemon=True,
            )
            self.thread.start()
            self.browser_control_calls += 1
            self.context = browser.new_context()
            self.browser_control_calls += 1
            self.page = self.context.new_page()
            self.browser_control_calls += 1
            self.page.set_default_timeout(10000)
            self.page.on("request", lambda _: self._network_event(False))
            self.page.on("requestfailed", lambda _: self._network_event(True))
            self.browser_control_calls += 1
            self.page.goto(
                f"http://127.0.0.1:{self.server.server_address[1]}/", wait_until="load"
            )
            self.setup_ns = time.perf_counter_ns() - self.started
        except Exception:
            self.close()
            raise

    def _network_event(self, failed):
        if failed:
            self.network_failures += 1
        else:
            self.network_requests += 1

    def _charge(self, action):
        if self.calls >= self.budget:
            raise BudgetExhausted()
        self.calls += 1
        self.last = action
        self.events.append(
            {"action": action, "at_ns": time.perf_counter_ns() - self.started}
        )

    def _click(self, action):
        self.browser_control_calls += 1
        prior = self.page.locator("#result").get_attribute("data-sequence")
        self.browser_control_calls += 1
        self.page.locator("#" + action).click()
        self.dom_actions += 1
        self.browser_control_calls += 1
        self.page.wait_for_function(
            "prior => document.querySelector('#result').dataset.sequence !== prior",
            arg=prior,
        )
        self.browser_control_calls += 1
        result = json.loads(self.page.locator("#result").inner_text())
        self.events[-1]["reply"] = result
        return result

    def _fill(self, key, goal, invocation):
        for field, value in (
            ("Record", str(key)),
            ("Content", goal),
            ("Invocation", invocation),
        ):
            self.browser_control_calls += 1
            self.page.get_by_label(field, exact=True).fill(value)
            self.dom_actions += 1

    def inspect(self):
        self._charge("inspect")
        self.reads += 1
        result = self._click("inspect")
        self.view = result.get("body") if result.get("http_status") == 200 else None
        self.failed_reads = self.failed_reads + 1 if self.view is None else 0
        self.events[-1]["observation"] = self.view
        if self.view and self.view["complete"] and self.complete_ns is None:
            self.complete_ns = time.perf_counter_ns() - self.started
        return self.view

    def stage(self):
        self._charge("stage")
        if not self.view or self.view["complete"]:
            return
        key = self.view["index"]
        self._fill(key, self.task["goals"][key], self.task["id"] + ":" + str(key))
        result = self._click("stage")
        self.writes += result.get("http_status") == 200

    def apply(self):
        self._charge("apply")
        if not self.view or self.view["complete"]:
            return
        key = self.view["index"]
        self._fill(key, self.task["goals"][key], self.task["id"] + ":" + str(key))
        result = self._click("apply")
        if result.get("transport_error"):
            self.lost_replies += 1
            self.view = None
        elif result.get("http_status") == 200:
            self.writes += result.get("body", {}).get("status") == "applied"

    def ensure(self):
        if self.view is None or self.view["complete"]:
            self.inspect()
            return
        if not self.view["staged"]:
            self.stage()
        self.apply()
        self.last = "ensure"

    def close(self):
        if self.closed:
            return
        before = time.perf_counter_ns()
        self.closed = True
        try:
            if self.context:
                self.browser_control_calls += 1
                self.context.close()
        finally:
            if self.server:
                if self.thread and self.thread.is_alive():
                    self.server.shutdown()
                    self.thread.join(timeout=2)
                self.server.server_close()
            self.cleanup_ns = time.perf_counter_ns() - before

    def score(self, claimed):
        facts = self.owner.audit()  # Read actual owner bytes; DOM is not an oracle.
        self.close()
        return {
            **facts,
            "claimed_success": claimed,
            "false_success": claimed and not facts["complete"],
            "primitive_calls": self.calls,
            "owner_requests": len(self.owner.calls),
            "independent_oracle_queries": 1,
            "lost_replies": self.lost_replies,
            "duration_ns": time.perf_counter_ns() - self.started,
            "setup_ns": self.setup_ns,
            "cleanup_ns": self.cleanup_ns,
            "completion_observed_ns": self.complete_ns,
            "dom_actions": self.dom_actions,
            "network_requests": self.network_requests,
            "browser_control_calls": self.browser_control_calls,
            "network_failures": self.network_failures,
            "http_requests": self.http_requests,
            "readback_queries": self.reads,
            "acknowledged_write_transactions": self.writes,
            "events": self.events,
            "real_browser_executed": True,
            "scope": "controlled loopback page; filesystem owner; same UID; no independent trust domain",
        }


def launch_browser(playwright, executable_path=None):
    try:
        options = {"headless": True, "timeout": 20000}
        if executable_path:
            options["executable_path"] = str(executable_path)
        return playwright.chromium.launch(**options)
    except Exception as error:
        raise BrowserUnavailable(str(error)[:3000]) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    rows = []
    report = {
        "status": "NOT_RUN",
        "real_browser_executed": False,
        "production_adoption": False,
        "rows": rows,
    }
    exit_code = 2
    try:
        from playwright.sync_api import sync_playwright
        from run import macro

        with (
            sync_playwright() as playwright,
            tempfile.TemporaryDirectory(prefix="act3-browser-") as folder,
        ):
            before = time.perf_counter_ns()
            browser = launch_browser(playwright, args.browser_executable)
            report["browser_launch_ns"] = time.perf_counter_ns() - before
            report["browser_version"] = browser.version
            report["browser_launched"] = True
            try:
                for version in (1, 2):
                    for fault in (
                        "normal",
                        "lost_reply",
                        "partial_failure",
                        "opaque_after_apply",
                    ):
                        task = {
                            "id": f"browser/v{version}/{fault}",
                            "version": version,
                            "fault": fault,
                            "goals": [f"goal-{version}-{i}" for i in range(3)],
                        }
                        destination = BrowserDestination(
                            Path(folder) / f"{version}-{fault}", task, browser
                        )
                        report["real_browser_executed"] = True
                        claimed = False
                        try:
                            for _ in range(2 * destination.budget):
                                action = macro(destination)
                                if action == "stop":
                                    view = destination.inspect()
                                    claimed = bool(view and view["complete"])
                                    break
                                getattr(destination, action)()
                        except BudgetExhausted:
                            pass
                        finally:
                            row = destination.score(claimed) | {
                                "task_id": task["id"],
                                "fault": fault,
                            }
                        rows.append(row)
            finally:
                before = time.perf_counter_ns()
                browser.close()
                report["browser_close_ns"] = time.perf_counter_ns() - before
            passed = (
                all(
                    not r["false_success"]
                    and not r["duplicate_effects"]
                    and (
                        r["claimed_success"]
                        if r["fault"] != "opaque_after_apply"
                        else not r["claimed_success"]
                    )
                    for r in rows
                )
                and len(rows) == 8
            )
            report.update(
                status="ENGINEERING_PASS" if passed else "ENGINEERING_FAIL",
                real_browser_executed=True,
                episodes=len(rows),
                rows=rows,
                learning_gain_qualified=False,
            )
            exit_code = 0 if passed else 1
    except (ImportError, BrowserUnavailable) as error:
        report["blocker"] = f"{type(error).__name__}: {error}"
        if report["real_browser_executed"]:
            report["status"] = "ENGINEERING_FAIL"
            exit_code = 1
    except Exception as error:
        report.update(
            status="ENGINEERING_FAIL", blocker=f"{type(error).__name__}: {error}"
        )
        exit_code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("status", "real_browser_executed", "production_adoption")
            }
        )
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
