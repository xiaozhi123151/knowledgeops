import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr

from knowledgeops.agent.tools import tool_definitions
from knowledgeops.providers.embedding import APIEmbedding
from knowledgeops.providers.llm import APILLM


async def test_openai_compatible_tool_protocol(settings):
    settings.llm_model = 'fixture-tool-model'
    settings.llm_api_key = SecretStr('test-only')
    provider = APILLM(settings)
    await provider.client.close()
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == '/v1/chat/completions'
        assert body['tool_choice'] == 'required' and body['parallel_tool_calls'] is False
        assert body['max_tokens'] == 2000 and len(body['tools']) == 3
        return httpx.Response(200,json={'id':'fixture','object':'chat.completion','created':0,
            'model':'fixture-tool-model','choices':[{'index':0,'finish_reason':'tool_calls','message':{
                'role':'assistant','content':None,'tool_calls':[{'id':'call_1','type':'function',
                'function':{'name':'knowledge_search','arguments':'{"query":"Redis"}'}}]}}],
            'usage':{'prompt_tokens':8,'completion_tokens':4,'total_tokens':12}})
    provider.client = AsyncOpenAI(api_key='test-only',base_url='https://fixture.invalid/v1',max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        message,usage = await provider.complete([{'role':'user','content':'Redis'}],tool_definitions())
        assert usage == 12 and message['tool_calls'][0]['function']['name'] == 'knowledge_search'
        assert provider.client.max_retries == 0
    finally:
        await provider.close()


async def test_embedding_response_order_and_dimension(settings):
    settings.embedding_model = 'fixture-embedding'
    settings.embedding_api_key = SecretStr('test-only')
    settings.embedding_dimensions = 8
    provider = APIEmbedding(settings)
    await provider.client.close()
    def handler(request):
        assert request.url.path == '/v1/embeddings'
        return httpx.Response(200,json={'object':'list','model':'fixture-embedding',
            'data':[{'object':'embedding','index':1,'embedding':[1.0]*8},
                    {'object':'embedding','index':0,'embedding':[0.5]*8}],
            'usage':{'prompt_tokens':2,'total_tokens':2}})
    provider.client = AsyncOpenAI(api_key='test-only',base_url='https://fixture.invalid/v1',max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        result = await provider.embed(['first','second'])
        assert result[0] == [0.5]*8 and result[1] == [1.0]*8
        provider.dimensions = 16
        with pytest.raises(ValueError,match='DIMENSION'):
            await provider.embed(['first','second'])
    finally:
        await provider.close()
