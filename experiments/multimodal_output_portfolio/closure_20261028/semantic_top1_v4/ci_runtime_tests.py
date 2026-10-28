"""No-model fixtures for cgroup mapping, hierarchy and explicit root observations."""
import unittest

from .ci_runtime import observe

MEM = 'MemTotal: 8192 kB\nMemAvailable: 4096 kB\n'
MOUNT = '29 1 0:25 / /cg rw - cgroup2 cgroup2 rw\n'
STATUS = 'VmRSS: 100 kB\nVmHWM: 120 kB\n'


def inspect(cgroup, files, mount=MOUNT):
    def read(path):
        if path not in files:
            raise FileNotFoundError(path)
        return files[path]
    return observe(MEM, cgroup, mount, STATUS, read)


class ResourceGuards(unittest.TestCase):
    def test_nested_parent_is_more_restrictive(self):
        value = inspect('0::/a/b\n', {'/cg/a/b/memory.current': '100', '/cg/a/b/memory.max': '1000',
                                      '/cg/a/memory.current': '450', '/cg/a/memory.max': '500'})
        self.assertEqual(50, value['effective_headroom_bytes'])
        self.assertEqual(3, len(value['cgroup_ancestor_observations']))
        self.assertFalse(value['invisible_ancestor_limits_known'])

    def test_namespace_root_retains_its_own_real_cap(self):
        value = inspect('0::/\n', {'/cg/memory.current': '45', '/cg/memory.max': '100'})
        self.assertEqual(55, value['effective_headroom_bytes'])

    def test_true_visible_root_without_files_is_explicit_host_observation(self):
        value = inspect('0::/\n', {})
        self.assertEqual(4096 * 1024, value['effective_headroom_bytes'])
        self.assertEqual('host_observation_without_finite_visible_cap', value['observation_status'])
        self.assertFalse(value['observation_is_future_memory_guarantee'])

    def test_partial_or_nonroot_missing_pair_blocks(self):
        for cgroup, files in [('0::/\n', {'/cg/memory.current': '1'}), ('0::/a\n', {})]:
            with self.subTest(cgroup=cgroup):
                self.assertEqual(0, inspect(cgroup, files)['effective_headroom_bytes'])

    def test_multiple_mappings_and_traversal_block(self):
        duplicate = MOUNT + '30 1 0:25 / /other rw - cgroup2 cgroup2 rw\n'
        self.assertEqual(0, inspect('0::/\n', {}, duplicate)['effective_headroom_bytes'])
        self.assertEqual(0, inspect('0::/a/../b\n', {})['effective_headroom_bytes'])

    def test_mount_escapes_are_decoded_and_membership_root_is_resolved(self):
        mount = '29 1 0:25 /parent /cg\\040space rw - cgroup2 cgroup2 rw\n'
        value = inspect('0::/parent/child\n', {'/cg space/child/memory.current': '10',
                                              '/cg space/child/memory.max': '40',
                                              '/cg space/memory.current': '10', '/cg space/memory.max': 'max'}, mount)
        self.assertEqual(30, value['effective_headroom_bytes'])
        self.assertEqual('/cg space/child', value['current_cgroup_path'])

    def test_unlimited_child_does_not_erase_parent_cap(self):
        value = inspect('0::/a/b\n', {'/cg/a/b/memory.current': '100', '/cg/a/b/memory.max': 'max',
                                      '/cg/a/memory.current': '400', '/cg/a/memory.max': '500'})
        self.assertEqual(100, value['effective_headroom_bytes'])

    def test_nonroot_bind_mount_missing_interfaces_blocks(self):
        mount = '29 1 0:25 /parent /cg rw - cgroup2 cgroup2 rw\n'
        self.assertEqual(0, inspect('0::/parent\n', {}, mount)['effective_headroom_bytes'])

    def test_invalid_memory_value_blocks(self):
        for value in ('-1', 'unknown', ''):
            with self.subTest(value=value):
                measured = inspect('0::/\n', {'/cg/memory.current': value, '/cg/memory.max': '100'})
                self.assertEqual(0, measured['effective_headroom_bytes'])


if __name__ == '__main__':
    unittest.main()
