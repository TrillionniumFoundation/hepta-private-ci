#!/usr/bin/env python3
"""Bounded query-only inspection of this process/thread and an existing linked token.

No token creation/adjustment/installation, process launch, privileges, ACLs or
accounts are changed. Import is portable; WinDLL loading occurs only on Windows.
"""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import sys

U32 = C.c_uint32
I32 = C.c_int32
HANDLE = C.c_void_p
MAX_INFORMATION = 1_048_576
MAX_GROUPS = 4096
TOKEN_QUERY = 0x0008
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_TOKEN = 1008
OWNER = 0x8
ENABLED = 0x4
DENY_ONLY = 0x10

class SidAndAttributes(C.Structure):
    _fields_ = [('sid', C.c_void_p), ('attributes', U32)]

class TokenGroups(C.Structure):
    _fields_ = [('count', U32), ('groups', SidAndAttributes * 1)]

class Luid(C.Structure):
    _fields_ = [('low', U32), ('high', I32)]

class LuidAndAttributes(C.Structure):
    _fields_ = [('luid', Luid), ('attributes', U32)]

class TokenPrivileges(C.Structure):
    _fields_ = [('count', U32), ('privileges', LuidAndAttributes * 1)]

def owner_eligible(attributes, same_user):
    return bool(attributes & OWNER and attributes & ENABLED and not attributes & DENY_ONLY and not same_user)

def span(buffer, pointer, size):
    start = C.addressof(buffer)
    offset = pointer - start
    if offset < 0 or size < 0 or offset + size > C.sizeof(buffer):
        raise ValueError('token pointer/length outside bounded returned buffer')
    return C.string_at(pointer, size)

def sid_text(buffer, pointer):
    if not pointer:
        raise ValueError('null SID')
    header = span(buffer, pointer, 8)
    revision, count = header[:2]
    if revision != 1 or count > 15:
        raise ValueError('invalid SID header')
    raw = span(buffer, pointer, 8 + 4 * count)
    authority = int.from_bytes(raw[2:8], 'big')
    values = [str(int.from_bytes(raw[x:x + 4], 'little')) for x in range(8, len(raw), 4)]
    return '-'.join(['S', str(revision), str(authority)] + values)

def struct_at(buffer, cls, offset=0):
    raw = span(buffer, C.addressof(buffer) + offset, C.sizeof(cls))
    return cls.from_buffer_copy(raw)

def scalar(buffer):
    return struct_at(buffer, U32).value

class WindowsQueries:
    def __init__(self):
        if sys.platform != 'win32':
            raise RuntimeError('native Windows query runner required; no emulated token claim')
        self.last_error = C.get_last_error
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.security = C.WinDLL('advapi32', use_last_error=True)
        def bind(dll, name, args, result):
            fn = getattr(dll, name); fn.argtypes = args; fn.restype = result; return fn
        self.process = bind(self.kernel, 'GetCurrentProcess', [], HANDLE)
        self.thread = bind(self.kernel, 'GetCurrentThread', [], HANDLE)
        self.close = bind(self.kernel, 'CloseHandle', [HANDLE], I32)
        self.open_process = bind(self.security, 'OpenProcessToken', [HANDLE, U32, C.POINTER(HANDLE)], I32)
        self.open_thread = bind(self.security, 'OpenThreadToken', [HANDLE, U32, I32, C.POINTER(HANDLE)], I32)
        self.information = bind(self.security, 'GetTokenInformation', [HANDLE, I32, C.c_void_p, U32, C.POINTER(U32)], I32)

    def query(self, token, information_class):
        length = U32()
        result = self.information(token, information_class, None, 0, C.byref(length))
        error = self.last_error()
        if result or error != ERROR_INSUFFICIENT_BUFFER:
            raise OSError(error, 'unexpected token size-query result')
        if not 0 < length.value <= MAX_INFORMATION:
            raise ValueError('token information exceeds bound')
        capacity = length.value
        buffer = C.create_string_buffer(capacity)
        if not self.information(token, information_class, buffer, capacity, C.byref(length)):
            raise OSError(self.last_error(), 'token information query failed')
        if length.value > capacity:
            raise ValueError('token information grew beyond supplied buffer')
        # Parsing bounds use the OS returned extent, not unused allocation bytes.
        if length.value != capacity:
            raise ValueError('token size changed between query calls; no uncertain snapshot')
        return buffer

    def facts(self, token):
        user = self.query(token, 1)
        user_sid = sid_text(user, struct_at(user, SidAndAttributes).sid)
        groups = self.query(token, 2)
        count = scalar(groups)
        if count > MAX_GROUPS:
            raise ValueError('too many token groups')
        observed = []
        for index in range(count):
            value = struct_at(groups, SidAndAttributes,
                TokenGroups.groups.offset + index * C.sizeof(SidAndAttributes))
            sid = sid_text(groups, value.sid)
            observed.append({'sid': sid, 'attributes': value.attributes,
                'owner_eligible': owner_eligible(value.attributes, sid == user_sid)})
        owner = self.query(token, 4)
        owner_sid = sid_text(owner, struct_at(owner, HANDLE).value)
        integrity = self.query(token, 25)
        integrity_sid = sid_text(integrity, struct_at(integrity, SidAndAttributes).sid)
        privileges = self.query(token, 3)
        count = scalar(privileges)
        if count > 256:
            raise ValueError('too many token privileges')
        privilege_facts = []
        for index in range(count):
            item = struct_at(privileges, LuidAndAttributes,
                TokenPrivileges.privileges.offset + index * C.sizeof(LuidAndAttributes))
            privilege_facts.append({'luid_low': item.luid.low, 'luid_high': item.luid.high,
                'attributes': item.attributes})
        return {'user_sid': user_sid, 'default_owner_sid': owner_sid, 'groups': observed,
            'token_type': scalar(self.query(token, 8)), 'elevation_type': scalar(self.query(token, 18)),
            'elevated': bool(scalar(self.query(token, 20))),
            'has_ever_been_filtered': bool(scalar(self.query(token, 21))),
            'is_app_container': bool(scalar(self.query(token, 29))),
            'integrity_sid': integrity_sid, 'privileges': privilege_facts,
            'owner_capable_sid': next((x['sid'] for x in observed if x['owner_eligible']), None)}

def error_record(error):
    return {'type': type(error).__name__, 'code': getattr(error, 'errno', None), 'message': str(error)}

def inspect(api=None):
    result = {'schema': 'a32.sshsig-token-probe.v1', 'pid': os.getpid(),
        'query_only': True, 'thread_impersonating': None, 'process': None,
        'owner_capable_sid': None, 'linked_token': {'status': 'not_queried'}, 'query_errors': [],
        'normal_user_execution_proved': False, 'derived_token_created': False}
    try:
        api = api or WindowsQueries()
        thread = HANDLE()
        if api.open_thread(api.thread(), TOKEN_QUERY, 1, C.byref(thread)):
            result['thread_impersonating'] = True
            api.close(thread)
            raise RuntimeError('active thread impersonation is not an admitted runner identity')
        error = api.last_error()
        if error != ERROR_NO_TOKEN:
            raise OSError(error, 'thread token absence is uncertain')
        result['thread_impersonating'] = False
        token = HANDLE()
        if not api.open_process(api.process(), TOKEN_QUERY, C.byref(token)):
            raise OSError(api.last_error(), 'process TOKEN_QUERY failed')
        try:
            result['process'] = api.facts(token)
            result['owner_capable_sid'] = result['process']['owner_capable_sid']
            try:
                linked = struct_at(api.query(token, 19), HANDLE).value
                if not linked:
                    raise ValueError('null linked token handle')
                try:
                    result['linked_token'] = {'status': 'observed_existing', 'facts': api.facts(linked),
                        'execution_or_launch_proved': False}
                finally:
                    api.close(linked)
            except (OSError, ValueError) as error:
                result['linked_token'] = {'status': 'unavailable_or_query_failed', 'error': error_record(error),
                    'execution_or_launch_proved': False}
        finally:
            api.close(token)
    except (OSError, ValueError, RuntimeError) as error:
        result['query_errors'].append(error_record(error))
    return result

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = inspect()
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    return int(bool(result['query_errors']))

if __name__ == '__main__':
    raise SystemExit(main())
