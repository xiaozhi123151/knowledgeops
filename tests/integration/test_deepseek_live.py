"""REAL DeepSeek calls. No mock LLM responses; retrieval-model substitutes are labeled in reports."""
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

from scripts.probe_deepseek import probe
from scripts.validate_deepseek import run_validation

pytestmark = [pytest.mark.live,pytest.mark.deepseek_live]


@pytest.fixture
def real_deepseek_key():
    if os.getenv('KO_RUN_DEEPSEEK_TESTS') == '0':
        pytest.skip('Real DeepSeek explicitly disabled; offline regression must not make paid API calls')
    env = {**dotenv_values(),**os.environ}
    if not (env.get('DEEPSEEK_API_KEY') or env.get('KO_DEEPSEEK_API_KEY')):
        pytest.skip('UNVERIFIED: DEEPSEEK_API_KEY not configured; no real model results fabricated')


async def test_real_non_thinking_tool_selection(real_deepseek_key,tmp_path):
    result = await probe(tmp_path)
    assert result['passed'], result.get('error')
    assert result['model']=='deepseek-flash' and result['thinking']=='disabled'
    assert result['budget']['llm_calls']==1 and result['budget']['tokens']>0
    assert not result['budget']['estimated']
    assert not result['response']['reasoning_content_present']


async def test_real_version_research_and_failure_recovery(real_deepseek_key,tmp_path):
    root = Path(os.environ.get('KO_DEEPSEEK_TEST_DATA_DIR',str(tmp_path)))
    result = await run_validation(root,cases=3)
    assert result['passed'], [
        {'name':row['name'],'status':row.get('status'),'error':row.get('error'),
         'versions':row.get('cited_versions'),'budget_consistent':row.get('budget_consistent')}
        for row in result['cases']]
    assert len(result['sources'])>=3
    assert result['summary']['invalid_model_function_calls']==0
    assert result['summary']['citations']==result['summary']['valid_citations']>0
    for row in result['cases']:
        assert row['budget_consistent'] and row['unknown_acknowledged']
        assert all(not response['reasoning_content_present'] for response in row['llm_responses'])
        assert row['budget']['tokens']<=row['limits']['token_budget']
    recovery = result['cases'][2]
    assert recovery['injected_local_failures']==1
    assert recovery['tool_attempts']==recovery['tool_completed']+1
