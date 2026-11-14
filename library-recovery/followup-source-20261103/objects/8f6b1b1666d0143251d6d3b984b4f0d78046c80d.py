import hashlib, math, unittest
import torch


def nearest_rank(values, p):
    if not values:
        raise ValueError('empty latency samples')
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)]


def backend_digest(model):
    h=hashlib.sha256(); count=0
    for name,param in sorted(model.named_parameters()):
        assert param.device.type=='cpu' and torch.isfinite(param).all()
        h.update(name.encode()+b'\0')
        h.update(param.detach().contiguous().reshape(-1).view(torch.uint8).numpy().tobytes())
        count+=param.numel()
    return h.hexdigest(),count


class TestHostedRegressions(unittest.TestCase):
    def test_nearest_rank_p95_twenty(self):
        self.assertEqual(nearest_rank(range(20), .95), 18)
    def test_nearest_rank_p95_and_p99(self):
        self.assertEqual(nearest_rank(range(40), .95), 37)
        self.assertEqual(nearest_rank(range(100), .95), 94)
        self.assertEqual(nearest_rank(range(100), .99), 98)
        self.assertEqual(nearest_rank(range(101), .99), 99)
    def test_bfloat16_tensor_native_raw_byte_length(self):
        m = torch.nn.Linear(384, 2).to(dtype=torch.bfloat16).eval()
        for param in m.parameters(): param.requires_grad_(False)
        digest, count=backend_digest(m)
        self.assertEqual(count, 770)
        self.assertEqual(len(digest),64)
        for param in m.parameters():
            self.assertEqual(len(param.detach().contiguous().view(torch.uint8).numpy().tobytes()), param.numel()*param.element_size())
    def test_zero_dim_mixed_bfloat16_float32_parameters(self):
        m=torch.nn.Linear(16,4).to(dtype=torch.bfloat16).eval()
        m.register_parameter('scalar_bf16',torch.nn.Parameter(torch.tensor(0.5,dtype=torch.bfloat16),requires_grad=False))
        m.register_parameter('scalar_f32',torch.nn.Parameter(torch.tensor(0.5,dtype=torch.float32),requires_grad=False))
        for p in m.parameters():p.requires_grad_(False)
        got,count=backend_digest(m)
        self.assertEqual(count,70)
        manually=hashlib.sha256()
        for name,parameter in sorted(m.named_parameters()):
            flat=parameter.detach().contiguous().reshape(-1)
            payload=flat.view(torch.uint8).numpy().tobytes()
            self.assertEqual(len(payload),parameter.numel()*parameter.element_size())
            manually.update(name.encode()+b'\0')
            manually.update(payload)
        self.assertEqual(got,manually.hexdigest())

    def test_float32_retains_previous_hash_semantics(self):
        m=torch.nn.Linear(384,2).eval()
        for p in m.parameters():p.requires_grad_(False)
        h=hashlib.sha256()
        for name,param in sorted(m.named_parameters()):
            h.update(name.encode()+b'\0')
            h.update(param.detach().contiguous().numpy().tobytes())
        self.assertEqual(backend_digest(m)[0], h.hexdigest())
    def test_tensor_mutation_changes_digest(self):
        m=torch.nn.Linear(16,2).to(dtype=torch.bfloat16).eval()
        before=backend_digest(m)[0]
        with torch.no_grad():m.bias[0]+=1
        self.assertNotEqual(backend_digest(m)[0], before)

if __name__=='__main__': unittest.main()
