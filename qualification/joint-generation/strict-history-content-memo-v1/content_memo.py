"""One-history, bounded, exact fresh-bytes SHA memo. No path or stat caching."""
import hashlib
class ContentMemo:
    def __init__(self):
        self.cache={}
        self.stats={'calls':0,'hash_calls':0,'hash_bytes':0,'hits':0,'entries':0,'retained_payload_bytes':0}
    def __call__(self,raw):
        if type(raw)is not bytes:raise ValueError('exact bytes only')
        self.stats['calls']+=1
        if len(raw)<=4096 and raw in self.cache:
            self.stats['hits']+=1
            return self.cache[raw]
        digest=hashlib.sha256(raw).hexdigest()
        self.stats['hash_calls']+=1;self.stats['hash_bytes']+=len(raw)
        if len(raw)<=4096 and len(self.cache)<16:
            self.cache[raw]=digest;self.stats['entries']=len(self.cache)
            self.stats['retained_payload_bytes']+=len(raw)
        return digest
