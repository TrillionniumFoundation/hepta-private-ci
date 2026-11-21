"""Small adversarial controls for the offline receipt and weight reader."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from audit_financial_source import (canonical, parse_head, read_receipt, sha,
                                    static_assignment, strict, verify_chain)


def head_bytes():
    header = {'value.bias': {'dtype':'F32','shape':[1],'data_offsets':[0,4]},
              'value.weight': {'dtype':'F32','shape':[1,768],'data_offsets':[4,3076]}}
    raw_header = canonical(header)
    return struct.pack('<Q',len(raw_header))+raw_header+struct.pack('<769f',-.25,*([0.]*768))


class ReaderControls(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_JSON_KEY'):
            strict('{"x":1,"x":2}')

    def test_nonfinite_json_rejected(self):
        with self.assertRaisesRegex(ValueError,'NONFINITE_JSON'):
            strict('{"x":NaN}')

    def test_complete_f32_layout(self):
        raw = head_bytes(); parsed = parse_head(raw,sha(raw))
        self.assertEqual(parsed['value.bias'],(-.25,))
        self.assertEqual(len(parsed['value.weight']),768)

    def test_changed_weight_bytes_rejected(self):
        raw = head_bytes(); changed = raw[:-1]+bytes([raw[-1]^1])
        with self.assertRaisesRegex(ValueError,'HEAD_BYTES'):
            parse_head(changed,sha(raw))

    def test_nonfinite_tensor_rejected(self):
        raw = head_bytes(); changed = raw[:-4]+struct.pack('<f',float('inf'))
        with self.assertRaisesRegex(ValueError,'HEAD_NONFINITE'):
            parse_head(changed,sha(changed))

    def test_unknown_tensor_layout_rejected(self):
        raw = head_bytes().replace(b'value.bias',b'value.biAs',1)
        with self.assertRaisesRegex(ValueError,'HEAD_TENSOR_NAMES'):
            parse_head(raw,sha(raw))

    def test_static_arithmetic_without_execution(self):
        self.assertEqual(static_assignment('RULE={"horizon":14*86400000}', 'RULE'),
                         {'horizon':1209600000})
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_STATIC_EXPRESSION'):
            static_assignment('RULE=__import__("os")', 'RULE')

    def test_changed_receipt_text_rejected(self):
        data = {'truncated':False,'files':[{'path':'/synthetic/receipt.json',
                'eof':True,'size':2,'text':'{}','sha256':sha(b'[]')} ]}
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'capture.json';path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'READBACK_SHA256'):
                read_receipt(path)

    def test_chain_rejects_truncation(self):
        with self.assertRaisesRegex(ValueError,'UNCOMMITTED_CAPTURE_TAIL'):
            verify_chain('{}','x'*64,'p'*64)


if __name__ == '__main__': unittest.main()
