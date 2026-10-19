"""Download public, first-party version documents without attaching any model credentials."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx

from scripts.common import ROOT, write_json

SOURCES = [
    ('DeepSeek-V2', 'https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V2/main/README.md'),
    ('DeepSeek-V3', 'https://raw.githubusercontent.com/deepseek-ai/DeepSeek-V3/main/README.md'),
    ('DeepSeek-V4.1-Flash', 'https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/raw/main/README.md'),
]


def fetch_documents(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    with httpx.Client(timeout=30, follow_redirects=True, headers={'User-Agent':'KnowledgeOps-validation/0.1'}) as client:
        for version, url in SOURCES:
            response = client.get(url)
            response.raise_for_status()
            data = response.content
            if len(data) < 300 or b'DeepSeek' not in data:
                raise ValueError('PUBLIC_DOCUMENT_INVALID')
            path = root / (version + '.md')
            path.write_bytes(data)
            entries.append({'version':version,'url':url,'resolved_url':str(response.url),
                'filename':path.name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
                'fetched_at_utc':datetime.now(timezone.utc).isoformat(),
                'etag':response.headers.get('etag')})
    write_json(root/'manifest.json',{'documents':entries,'credentials_attached':False})
    return entries


def main():
    entries = fetch_documents(ROOT/'data'/'deepseek_validation'/'documents')
    print(f'Downloaded {len(entries)} public first-party Markdown documents; manifest saved under data/.')


if __name__ == '__main__':
    main()
