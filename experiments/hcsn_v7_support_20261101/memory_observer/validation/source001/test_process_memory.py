"""Focused observer safety cases using owned fixture trees, not host scans."""

from pathlib import Path
import tempfile
import unittest

from process_memory import Identity, Observer, Unavailable, parse_stat


def stat(pid, ppid, started, name="worker with ) in name"):
    fields = ["R", str(ppid)] + ["0"] * 17 + [str(started), "8192", "2"]
    return f"{pid} ({name}) " + " ".join(fields) + "\n"


def process(root, pid, ppid, inner, started, pages, children):
    p = root / str(pid)
    p.mkdir()
    (p / "stat").write_text(stat(pid, ppid, started))
    (p / "status").write_text(f"Pid:\t{pid}\nPPid:\t{ppid}\nNSpid:\t{pid}\t{inner}\n")
    (p / "statm").write_text(f"99 {pages} 1 0 0 0 0\n")
    t = p / "task" / str(pid)
    t.mkdir(parents=True)
    if children is not None:
        (t / "children").write_text(" ".join(str(x) for x in children))


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        process(self.root, 901, 900, 2, 100, 10, [902])
        process(self.root, 902, 901, 3, 101, 20, [903])
        process(self.root, 903, 902, 4, 102, 30, [])
        (self.root / "self").symlink_to("901")
        self.observer = Observer(self.root, page_bytes=4096)
        self.me = self.observer.own_identity(expected_namespace_pid=2)

    def tearDown(self):
        self.temp.cleanup()

    def test_namespace_mapping_and_all_descendants(self):
        measured = self.observer.sample_family(self.me)
        self.assertTrue(measured["available"])
        self.assertTrue(measured["full_descendant_coverage"])
        self.assertEqual(measured["rss_sum_bytes"], 60 * 4096)
        self.assertEqual([x["identity"]["proc_pid"] for x in measured["members"]], [901, 902, 903])

    def test_proc_stat_parenthesis(self):
        self.assertEqual(parse_stat(stat(901, 900, 100)), (901, 900, 100))

    def test_reused_pid_is_unavailable_not_zero(self):
        old = self.observer.identity(902)
        (self.root / "902" / "stat").write_text(stat(902, 901, 999))
        observed = self.observer.sample_registered_set(self.me, [self.me, old])
        self.assertFalse(observed["available"])
        self.assertIsNone(observed["rss_sum_bytes"])

    def test_missing_namespace_mapping_fails_closed(self):
        (self.root / "902" / "status").write_text("Pid: 902\nPPid: 901\n")
        observed = self.observer.sample_family(self.me)
        self.assertFalse(observed["available"])
        self.assertIsNone(observed["rss_sum_bytes"])

    def test_missing_statm_fails_closed(self):
        (self.root / "903" / "statm").unlink()
        observed = self.observer.sample_family(self.me)
        self.assertFalse(observed["available"])
        self.assertIsNone(observed["rss_sum_bytes"])

    def test_missing_children_does_not_promote_registered_set(self):
        child = self.observer.register_owned_child(self.me, 3, self.observer.identity(902).record())
        grand = self.observer.register_owned_child(child, 4, self.observer.identity(903).record())
        (self.root / "901" / "task" / "901" / "children").unlink()
        family = self.observer.sample_family(self.me)
        registered = self.observer.sample_registered_set(self.me, [self.me, child, grand])
        self.assertFalse(family["available"])
        self.assertIsNone(family["rss_sum_bytes"])
        self.assertTrue(registered["available"])
        self.assertFalse(registered["full_descendant_coverage"])

    def test_wrong_spawn_pid_or_parent_rejected(self):
        handshake = self.observer.identity(902).record()
        with self.assertRaises(Unavailable):
            self.observer.register_owned_child(self.me, 99, handshake)
        with self.assertRaises(Unavailable):
            self.observer.register_owned_child(self.me, 4, self.observer.identity(903).record())

    def test_duplicate_members_do_not_double_count(self):
        observed = self.observer.sample_registered_set(self.me, [self.me, self.me])
        self.assertFalse(observed["available"])
        self.assertIsNone(observed["rss_sum_bytes"])

    def test_thread_children_are_combined_without_duplicates(self):
        task = self.root / "901" / "task" / "904"
        task.mkdir()
        (task / "children").write_text("902")
        measured = self.observer.sample_family(self.me)
        self.assertEqual(measured["rss_sum_bytes"], 60 * 4096)

    def test_inventory_bound_fails_closed(self):
        measured = Observer(self.root, page_bytes=4096, max_processes=2).sample_family(self.me)
        self.assertFalse(measured["available"])
        self.assertIsNone(measured["rss_sum_bytes"])


if __name__ == "__main__":
    unittest.main()
