import io
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from knowledgeops.config import Settings
from knowledgeops.ingestion.extract import extract
from knowledgeops.ingestion.web import fetch_page, resolve_public


def test_pdf_blank_and_encrypted():
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.showPage()
    c.save()
    with pytest.raises(ValueError, match='OCR_REQUIRED'):
        extract(buf.getvalue(), '.pdf')
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(io.BytesIO(buf.getvalue())))
    writer.encrypt('secret')
    encrypted = io.BytesIO()
    writer.write(encrypted)
    with pytest.raises(ValueError, match='ENCRYPTED_PDF'):
        extract(encrypted.getvalue(), '.pdf')


def test_chinese_text_pdf():
    from scripts.prepare_examples import make_chinese_pdf
    pages = extract(make_chinese_pdf(),'.pdf')
    assert pages[0].page == 1
    assert '混合检索' in pages[0].text and 'CrossEncoder' in pages[0].text


@pytest.mark.parametrize('ip', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1'])
def test_private_addresses(ip):
    with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', (ip, 80))]):
        with pytest.raises(ValueError, match='BLOCKED'):
            resolve_public('target.test', 80)


def test_redirect_revalidated():
    class Reply:
        status = 302
        def getheader(self, name, default=None):
            return 'http://127.0.0.1/internal' if name == 'Location' else default
    class Connection:
        def __init__(self, *args):
            pass
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            return Reply()
        def close(self):
            pass
    with patch('knowledgeops.ingestion.web.PinnedHTTPS', Connection), patch(
        'knowledgeops.ingestion.web.resolve_public', side_effect=['93.184.216.34', ValueError('URL_BLOCKED')]
    ) as resolver:
        with pytest.raises(ValueError, match='URL_BLOCKED'):
            fetch_page('https://example.com')
        assert resolver.call_count == 2


def test_config_live_no_silent_fallback():
    with pytest.raises(ValueError, match='required'):
        Settings(_env_file=None, mode='live')
    with pytest.raises(ValueError, match='overlap'):
        Settings(_env_file=None, chunk_size=100, chunk_overlap=120)


async def test_index_fingerprint_prevents_mixing(stack):
    settings, _, engine, _ = stack
    engine.fingerprint = 'changed'
    with pytest.raises(ValueError, match='INDEX_CONFIG_CHANGED'):
        await engine.initialize()
