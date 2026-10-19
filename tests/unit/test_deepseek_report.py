import json

from scripts.common import REPORTS
from scripts.deepseek_report import section


def test_report_preserves_real_failed_attempt_without_inventing_rates():
    # Recorded real exploratory run: valid API reply but zero tool executions, so the rate is undefined.
    failed = json.loads((REPORTS/'deepseek-attempt-02-tool-batch.json').read_text(encoding='utf-8'))
    text = '\n'.join(section(failed))
    assert 'FAIL' in text and '0/0 (n/a)' in text
    assert 'not full live retrieval-stack validation' in text
