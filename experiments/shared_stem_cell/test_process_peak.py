import unittest
from unittest.mock import patch, SimpleNamespace

from experiments.shared_stem_cell.process_peak import linux_lifetime_peak_rss_bytes


class PeakTests(unittest.TestCase):
    def test_linux_reads_real_process_lifetime_highwater_units(self):
        with patch("sys.platform", "linux"), patch("resource.getrusage",
                     return_value=SimpleNamespace(ru_maxrss=12345)):
            self.assertEqual(linux_lifetime_peak_rss_bytes(), 12345*1024)

    def test_unknown_platform_does_not_guess_rusage_units(self):
        with patch("sys.platform", "darwin"):
            self.assertIsNone(linux_lifetime_peak_rss_bytes())

    def test_invalid_or_unavailable_stays_null(self):
        with patch("sys.platform", "linux"):
            for size in (0, -2, float("nan"), float("inf"), 2.5):
                with self.subTest(size=size), patch("resource.getrusage",
                         return_value=SimpleNamespace(ru_maxrss=size)):
                    self.assertIsNone(linux_lifetime_peak_rss_bytes())
            with patch("resource.getrusage", side_effect=OSError("unavailable")):
                self.assertIsNone(linux_lifetime_peak_rss_bytes())


if __name__ == "__main__":
    unittest.main()
