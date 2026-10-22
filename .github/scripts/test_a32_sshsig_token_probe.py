import ctypes as C
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('a32_sshsig_token_probe.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class QueryProbeTests(unittest.TestCase):
    def test_only_enabled_non_deny_owner_other_than_user_is_eligible(self):
        self.assertTrue(probe.owner_eligible(12, False))
        for attributes, same in [(0, False), (8, False), (4, False), (10, False), (28, False), (12, True)]:
            self.assertFalse(probe.owner_eligible(attributes, same))

    def test_native_struct_widths_are_portable(self):
        self.assertEqual(C.sizeof(probe.U32), 4)
        self.assertEqual(C.sizeof(probe.Luid), 8)
        self.assertEqual(C.sizeof(probe.LuidAndAttributes), 12)

    def test_real_buffer_sid_parser(self):
        buffer = C.create_string_buffer(bytes([1, 2, 0, 0, 0, 0, 0, 5]) + (32).to_bytes(4, 'little') + (544).to_bytes(4, 'little'))
        self.assertEqual(probe.sid_text(buffer, C.addressof(buffer)), 'S-1-5-32-544')

    def test_unbounded_invalid_null_and_escaped_sids_reject(self):
        buffer = C.create_string_buffer(bytes([1, 16, 0, 0, 0, 0, 0, 5]))
        for pointer in [0, C.addressof(buffer), C.addressof(buffer) - 1, C.addressof(buffer) + 8]:
            with self.assertRaises(ValueError):
                probe.sid_text(buffer, pointer)

    def test_truncated_struct_rejects(self):
        with self.assertRaises(ValueError):
            probe.struct_at(C.create_string_buffer(2), probe.SidAndAttributes)

    def test_only_no_token_error_establishes_no_impersonation(self):
        class Api:
            error = probe.ERROR_NO_TOKEN
            active = False
            closed = []
            def thread(self): return -2
            def process(self): return -1
            def last_error(self): return self.error
            def close(self, handle): self.closed.append(handle)
            def open_thread(self, handle, rights, as_self, out):
                if self.active:
                    C.cast(out, C.POINTER(probe.HANDLE))[0] = 8
                return self.active
            def open_process(self, handle, rights, out):
                C.cast(out, C.POINTER(probe.HANDLE))[0] = 9
                return True
            def facts(self, token): return {'owner_capable_sid': None, 'elevated': False}
            def query(self, token, kind): raise OSError(1312, 'no existing linked token')
        api = Api()
        valid = probe.inspect(api)
        self.assertEqual(valid['query_errors'], [])
        self.assertFalse(valid['thread_impersonating'])
        self.assertIsNone(valid['owner_capable_sid'])
        self.assertEqual(valid['linked_token']['status'], 'unavailable_or_query_failed')
        self.assertFalse(valid['normal_user_execution_proved'])
        self.assertEqual(len(api.closed), 1)
        for code in [0, 5, 1347]:
            api.error = code
            failure = probe.inspect(api)
            self.assertTrue(failure['query_errors'])
            self.assertIsNone(failure['thread_impersonating'])
        api.active = True
        failure = probe.inspect(api)
        self.assertTrue(failure['query_errors'])
        self.assertTrue(failure['thread_impersonating'])

    @unittest.skipIf(__import__('sys').platform == 'win32', 'portable non-Windows-only failure contract')
    def test_non_windows_never_claims_token_evidence(self):
        result = probe.inspect()
        self.assertTrue(result['query_errors'])
        self.assertFalse(result['normal_user_execution_proved'])
        self.assertFalse(result['derived_token_created'])
        self.assertIsNone(result['owner_capable_sid'])

if __name__ == '__main__':
    unittest.main()
