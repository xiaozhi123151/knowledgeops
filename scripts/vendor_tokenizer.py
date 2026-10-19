"""Refresh the official reference tokenizer data with its upstream integrity hash."""
import hashlib
from pathlib import Path
from urllib.request import urlopen

URL = 'https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken'
SHA256 = '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7'


def main():
    with urlopen(URL, timeout=30) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('TOKENIZER_HASH_MISMATCH')
    path = Path(__file__).parents[1] / 'src' / 'knowledgeops' / 'providers' / 'cl100k_base.tiktoken'
    path.write_bytes(data)
    print(f'verified tokenizer: {len(data)} bytes, sha256={SHA256}')


if __name__ == '__main__':
    main()
