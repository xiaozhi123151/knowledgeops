import base64
import hashlib
from functools import lru_cache
from pathlib import Path

import tiktoken


@lru_cache(maxsize=1)
def reference_encoding():
    data = Path(__file__).with_name('cl100k_base.tiktoken').read_bytes()
    if hashlib.sha256(data).hexdigest() != '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7':
        raise ValueError('TOKENIZER_HASH_MISMATCH')
    ranks = {base64.b64decode(token): int(rank) for token, rank in (line.split() for line in data.splitlines())}
    return tiktoken.Encoding(name='ko-cl100k-reference', mergeable_ranks=ranks, special_tokens={},
        pat_str=r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s")
