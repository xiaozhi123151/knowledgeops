import json


class JSONOnlySerializer:
    """Graph state contains JSON primitives only. No pickle or dynamic object construction."""
    def dumps(self, obj):
        return json.dumps(obj, ensure_ascii=False).encode()

    def loads(self, data):
        return json.loads(data)

    def dumps_typed(self, obj):
        return 'json', self.dumps(obj)

    def loads_typed(self, data):
        kind, payload = data
        if kind != 'json':
            raise ValueError('UNSAFE_CHECKPOINT_TYPE')
        return self.loads(payload)
