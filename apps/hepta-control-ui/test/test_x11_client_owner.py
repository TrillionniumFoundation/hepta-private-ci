"""Check the libXRes return/error contract without connecting to a user display.

These boundary tests are not an X server qualification. The real native
harness separately checks its XRes server against the retained Shell child.
"""

import ctypes as C
import unittest
from unittest.mock import patch

from x11_client_owner import ClientIdValue, PID_MASK, XResOwner


class Reply:
    def __init__(self, status, pid=1234, mask=PID_MASK):
        self.status = status
        self.pid = pid
        self.value = (ClientIdValue * 1)()
        self.value[0].spec.mask = mask
        self.destroyed = False
        self.pid_read = False

    def XResQueryClientIds(self, _display, _count, _spec, count, values):
        C.cast(count, C.POINTER(C.c_long))[0] = 1
        C.cast(values, C.POINTER(C.POINTER(ClientIdValue)))[0] = self.value
        return self.status

    def XResGetClientPid(self, _value):
        self.pid_read = True
        return self.pid

    def XResClientIdsDestroy(self, _count, _values):
        self.destroyed = True


def connection(reply):
    owner = XResOwner.__new__(XResOwner)
    owner.handle = 1
    owner.xres = reply
    owner.version = [1, 2]
    return owner


class XResContractTests(unittest.TestCase):
    def test_x11_success_zero_decodes_and_frees_the_server_reply(self):
        reply = Reply(0)
        self.assertEqual(connection(reply).owner_pid(0xC00004), 1234)
        self.assertTrue(reply.pid_read)
        self.assertTrue(reply.destroyed)

    def test_nonzero_x11_error_cannot_be_mistaken_for_bool_success(self):
        for status in (1, 2, 3, -1):
            with self.subTest(status=status):
                reply = Reply(status)
                with self.assertRaisesRegex(RuntimeError, "QueryClientIds failed"):
                    connection(reply).owner_pid(0xC00004)
                self.assertFalse(reply.pid_read)
                self.assertTrue(reply.destroyed)

    def test_non_pid_record_is_not_decoded_as_a_local_pid(self):
        reply = Reply(0, mask=1)
        with self.assertRaisesRegex(RuntimeError, "mistyped"):
            connection(reply).owner_pid(0xC00004)
        self.assertFalse(reply.pid_read)
        self.assertTrue(reply.destroyed)

    def test_unknown_or_foreign_server_pid_cannot_authorize_the_window(self):
        for pid in (-1, 0, 1235):
            with self.subTest(pid=pid):
                with self.assertRaisesRegex(RuntimeError, "owner mismatch"):
                    connection(Reply(0, pid=pid)).require_pid(0xC00004, 1234)

    def test_multiple_owned_windows_are_not_reduced_to_the_first_visible_one(self):
        with patch("x11_client_owner.visible_windows", return_value=[0xC00004, 0xC00005]):
            with self.assertRaisesRegex(RuntimeError, "more than one"):
                connection(Reply(0)).find_visible(1234)


if __name__ == "__main__":
    unittest.main()
