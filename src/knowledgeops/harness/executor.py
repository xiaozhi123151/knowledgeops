import asyncio
import hashlib
import json
import time

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

from knowledgeops.agent.tools import TOOL_MODELS
from knowledgeops.providers.tokens import reference_encoding
from knowledgeops.storage.db import dumps


def transient(exc):
    return isinstance(exc, (TimeoutError, ConnectionError, httpx.TransportError,
                            APIConnectionError, APITimeoutError)) or (
        isinstance(exc, APIStatusError) and (exc.status_code == 429 or exc.status_code >= 500))


def cache_key(name, args):
    return name + ':' + hashlib.sha256(dumps(args).encode()).hexdigest()


def token_reservation(messages, tools, output_tokens):
    # Explicit reference tokenizer + framing margin. A compatible provider can use a different
    # tokenizer; actual returned usage remains authoritative, and missing usage stays estimated.
    count = len(reference_encoding().encode(dumps({'messages': messages, 'tools': tools})))
    return count + 32 * len(messages) + output_tokens + 256


class DurableHarness:
    def __init__(self, settings, store, task_id, owner, llm, trace=None):
        self.settings, self.store = settings, store
        self.task_id, self.owner, self.provider = task_id, owner, llm
        self.trace = trace

    def event(self, kind, data=None):
        self.store.event(self.task_id, kind, data)
        if self.trace:
            self.trace.emit(kind, {'task_id': self.task_id, 'mode': self.settings.mode, **(data or {})})

    async def step(self):
        self.store.reserve(self.task_id, self.owner, 'steps')
        self.event('agent_step')

    async def llm(self, messages, tools=None):
        key = cache_key('llm', {'messages': messages, 'tools': tools, 'model': self.provider.name})
        cached = self.store.cached(self.task_id, key)
        if cached is not None:
            self.event('llm_cache_hit')
            return cached
        reservation = token_reservation(messages, tools, self.settings.output_tokens)
        # Structural telemetry only: no prompts or source text. Repeated full context is visible in traces.
        content_hashes = [hashlib.sha256(str(m.get('content', '')).encode()).hexdigest()
                          for m in messages if m.get('role') == 'tool']
        evidence_chunks = []
        for m in messages:
            if m.get('role') == 'tool' and m.get('name') == 'knowledge_search':
                try:
                    payload = json.loads(m.get('content') or '{}')
                    evidence_chunks.extend(c['chunk_id'] for c in payload.get('evidence', {}).values())
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass
        context_metrics = {'input_messages': len(messages),
                           'input_characters': sum(len(str(m.get('content', ''))) for m in messages),
                           'tool_messages': len(content_hashes),
                           'duplicate_tool_messages': len(content_hashes)-len(set(content_hashes)),
                           'search_evidence_occurrences':len(evidence_chunks),
                           'unique_search_evidence_chunks':len(set(evidence_chunks)),
                           'repeated_search_evidence_chunks':len(evidence_chunks)-len(set(evidence_chunks)),
                           'request_fingerprint': key.split(':', 1)[1]}
        for attempt in range(self.settings.max_retries + 1):
            self.store.reserve(self.task_id, self.owner, 'llm_calls', reservation)
            self.event('llm_started', {'attempt': attempt + 1, 'reserved_tokens': reservation, **context_metrics})
            started = time.perf_counter()
            try:
                async with asyncio.timeout(self.settings.llm_timeout or self.settings.tool_timeout):
                    message, usage = await self.provider.complete(messages, tools, self.settings.output_tokens)
                self.store.settle(self.task_id, self.owner, reservation, usage)
                if not isinstance(message, dict) or message.get('role') != 'assistant':
                    raise ValueError('INVALID_LLM_OUTPUT')
                self.store.cache(self.task_id, self.owner, key, message)
                self.event('llm_completed', {'usage': usage, 'estimated': usage is None,
                    'elapsed_ms': (time.perf_counter() - started) * 1000,
                    **getattr(self.provider, 'last_call_metadata', {})})
                return message
            except Exception as exc:
                self.event('llm_error', {'type': type(exc).__name__, 'attempt': attempt + 1,
                    'status_code': exc.status_code if isinstance(exc, APIStatusError) else None,
                    'elapsed_ms': (time.perf_counter() - started) * 1000})
                if not transient(exc) or attempt == self.settings.max_retries:
                    raise
                await asyncio.sleep(.1 * 2**attempt)

    async def tool(self, name, arguments, fn):
        model = TOOL_MODELS.get(name)
        if not model:
            raise ValueError('TOOL_NOT_ALLOWED')
        parsed = model.model_validate(arguments)
        key = cache_key('tool:' + name, parsed.model_dump())
        cached = self.store.cached(self.task_id, key)
        if cached is not None:
            self.event('tool_cache_hit', {'name': name})
            return cached
        for attempt in range(self.settings.max_retries + 1):
            self.store.reserve(self.task_id, self.owner, 'tool_calls')
            self.event('tool_started', {'name': name, 'attempt': attempt+1})
            started = time.perf_counter()
            try:
                async with asyncio.timeout(self.settings.tool_timeout):
                    result = await fn(parsed)
                if not isinstance(result, dict):
                    raise ValueError('INVALID_TOOL_OUTPUT')
                self.store.cache(self.task_id, self.owner, key, result)
                self.event('tool_completed', {'name': name, 'elapsed_ms': (time.perf_counter()-started)*1000})
                return result
            except Exception as exc:
                self.event('tool_error', {'name': name, 'type': type(exc).__name__,
                                         'attempt': attempt+1, 'elapsed_ms': (time.perf_counter()-started)*1000})
                if not transient(exc) or attempt == self.settings.max_retries:
                    raise
                await asyncio.sleep(.1 * 2**attempt)
