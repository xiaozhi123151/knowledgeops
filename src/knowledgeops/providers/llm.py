import json
import time
import uuid

from openai import AsyncOpenAI


def call(name, arguments):
    return {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'call_' + uuid.uuid4().hex, 'type': 'function',
         'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}]}


class FakeLLM:
    """Deterministic protocol test double; it does not synthesize a semantic research answer."""
    name = 'offline-scripted-v1'

    async def complete(self, messages, tools=None, max_tokens=2000):
        if not tools:
            payload = json.loads(messages[-1]['content'])
            findings = [{'text': item['text'][:250], 'citation_ids': [cid]} for cid, item in payload.items()]
            return {'role': 'assistant', 'content': json.dumps({
                'agreements': findings, 'conflicts': [],
                'limitations': ['OFFLINE: comparison is an extractive test double, not semantic conflict detection.']})}, None
        last_user = max(i for i, m in enumerate(messages) if m['role'] == 'user')
        current = messages[last_user:]
        outputs = {m.get('name'): json.loads(m['content']) for m in current if m['role'] == 'tool'}
        if 'knowledge_search' not in outputs:
            return call('knowledge_search', {'query': messages[last_user]['content'], 'mode': 'hybrid',
                                             'rerank': True, 'top_k': 3}), None
        evidence = outputs['knowledge_search'].get('evidence', {})
        if evidence and 'compare_evidence' not in outputs:
            return call('compare_evidence', {'citation_ids': list(evidence)}), None
        findings = [{'text': chunk['text'][:250], 'citation_ids': [cid]} for cid, chunk in evidence.items()]
        return call('build_report', {
            'title': 'KnowledgeOps 离线证据报告',
            'conclusion': '以下为检索证据摘录（离线测试替身）。' if evidence else '证据不足。',
            'findings': findings, 'disagreements': [],
            'quotes': {cid: c['text'][:250] for cid, c in evidence.items()},
            'limitations': ['OFFLINE_TEST_DOUBLE: not a real LLM research-quality evaluation.'],
            'insufficient_evidence': not bool(evidence),
        }), None

    async def close(self):
        pass


class APILLM:
    def __init__(self, settings):
        self.name = settings.llm_model
        self.client = AsyncOpenAI(api_key=settings.llm_api_key.get_secret_value(),
                                  base_url=settings.llm_base_url,
                                  timeout=settings.llm_timeout or settings.tool_timeout, max_retries=0)
        self.last_call_metadata = {}

    def request_options(self, tools):
        return {'tools': tools, 'tool_choice': 'required', 'parallel_tool_calls': False} if tools else {}

    async def complete(self, messages, tools=None, max_tokens=2000):
        clean = [{k: v for k, v in m.items() if k != 'name' or m['role'] != 'tool'} for m in messages]
        kwargs = self.request_options(tools)
        self.last_call_metadata = {}
        started = time.perf_counter()
        response = await self.client.chat.completions.create(model=self.name, messages=clean,
                                                             max_tokens=max_tokens, **kwargs)
        if not response.choices:
            raise ValueError('LLM_EMPTY_RESPONSE')
        usage_details = response.usage.model_dump(exclude_none=True) if response.usage else None
        # No headers, request bodies, API error bodies, reasoning content or credentials enter telemetry.
        self.last_call_metadata = {
            'elapsed_ms': (time.perf_counter() - started) * 1000,
            'response_id': response.id, 'response_model': response.model,
            'finish_reason': response.choices[0].finish_reason,
            'prompt_tokens': usage_details.get('prompt_tokens') if usage_details else None,
            'completion_tokens': usage_details.get('completion_tokens') if usage_details else None,
            'total_tokens': usage_details.get('total_tokens') if usage_details else None,
            'cached_tokens': usage_details.get('prompt_cache_hit_tokens') if usage_details else None,
            'tool_call_count': len(response.choices[0].message.tool_calls or []),
            'reasoning_content_present': bool(getattr(response.choices[0].message,'reasoning_content',None)),
            'temperature': getattr(self, 'temperature', None),
        }
        message = response.choices[0].message.model_dump(exclude_none=True)
        message = {k: message[k] for k in ('role', 'content', 'tool_calls') if k in message}
        usage = response.usage.total_tokens if response.usage else None
        return message, usage

    async def close(self):
        await self.client.close()


class DeepSeekLLM(APILLM):
    """Official DeepSeek Chat Completions, explicitly non-thinking; same complete() contract."""
    def __init__(self, settings):
        if settings.deepseek_base_url.rstrip('/') != 'https://api.deepseek.com':
            raise ValueError('DeepSeek credentials may only be sent to the official HTTPS endpoint')
        if not settings.deepseek_api_key.get_secret_value():
            raise ValueError('DEEPSEEK_API_KEY is required')
        super().__init__(settings.model_copy(update={
            'llm_base_url': settings.deepseek_base_url,
            'llm_api_key': settings.deepseek_api_key,
            'llm_model': settings.deepseek_model,
        }))
        self.temperature = settings.deepseek_temperature

    def request_options(self, tools):
        # parallel_tool_calls is not part of the documented DeepSeek schema; the graph already
        # executes its bounded tool list serially. Thinking is disabled on comparison calls too.
        options = {'extra_body': {'thinking': {'type': 'disabled'}}, 'temperature': self.temperature}
        if tools:
            options.update(tools=tools, tool_choice='required')
        else:
            # Internal comparison is structured JSON; tool-call argument validation remains unchanged.
            options['response_format'] = {'type': 'json_object'}
        return options


def make_llm(settings):
    provider = settings.resolved_llm_provider
    if provider == 'mock':
        return FakeLLM()
    if provider == 'deepseek':
        return DeepSeekLLM(settings)
    return APILLM(settings)
