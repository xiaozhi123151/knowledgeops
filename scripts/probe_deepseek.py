"""One real non-thinking tool-selection request, always accounted by the durable Harness."""
import asyncio
import json
import tempfile
import time
from pathlib import Path

from knowledgeops.agent.tools import TOOL_MODELS, tool_definitions
from knowledgeops.config import Settings
from knowledgeops.harness.executor import DurableHarness
from knowledgeops.providers.llm import DeepSeekLLM
from knowledgeops.storage.db import Database
from knowledgeops.storage.tasks import TaskStore
from scripts.common import REPORTS, metadata, write_json


async def probe(root):
    settings = Settings(mode='offline', llm_provider='deepseek', data_dir=root, output_tokens=512)
    store = TaskStore(Database(root), settings)
    task = store.create('research', {'question': 'Real API tool-selection probe'})
    owner = 'deepseek-probe'
    store.claim(task, owner)
    llm = DeepSeekLLM(settings)
    harness = DurableHarness(settings, store, task, owner, llm)
    result = {'metadata': metadata('real_deepseek_local_retrieval'), 'passed': False,
              'endpoint':settings.deepseek_base_url, 'model':llm.name, 'thinking':'disabled'}
    started = time.perf_counter()
    try:
        message = await harness.llm([{'role':'user','content':
            '请调用 knowledge_search 检索 DeepSeek-V2 的总参数量。只发起检索工具调用，不要直接回答。'}], tool_definitions())
        calls = message.get('tool_calls', [])
        assert calls, 'Model did not return tool calls'
        parsed = []
        for call in calls:
            function = call['function']
            args = json.loads(function['arguments'])
            TOOL_MODELS[function['name']].model_validate(args)
            parsed.append({'name':function['name'],'arguments':args})
        result.update(passed=True, tool_calls=parsed, response=llm.last_call_metadata)
        store.finish(task, owner, result={'tool_calls':parsed})
    except Exception as exc:
        # Never serialize arbitrary API exception strings or response bodies.
        result['error'] = {'type':type(exc).__name__, 'status_code':getattr(exc,'status_code',None)}
        store.finish(task, owner, error=type(exc).__name__)
    finally:
        result.update(elapsed_ms=(time.perf_counter()-started)*1000,
                      budget=store.get(task)['budget'], events=store.events(task))
        await llm.close()
    write_json(REPORTS/'deepseek-probe.json', result)
    return result


def main():
    with tempfile.TemporaryDirectory(prefix='ko-deepseek-probe-') as directory:
        result = asyncio.run(probe(Path(directory)))
    print(json.dumps({k:result[k] for k in ['passed','model','elapsed_ms','budget']}, indent=2))
    if not result['passed']:
        print(json.dumps(result['error']))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
