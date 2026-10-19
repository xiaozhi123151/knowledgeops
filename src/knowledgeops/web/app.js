/* All untrusted content is rendered with textContent; never interpreted as HTML. */
const $ = id => document.getElementById(id);
let session = null, activeTask = null, cursor = 0, pollGeneration = 0;
$('key').value = sessionStorage.getItem('ko-api-key') || '';
function node(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
function notice(text) { $('notice').textContent = text || ''; }
async function api(path, options = {}) {
  const headers = {'X-API-Key': $('key').value, ...(options.headers || {})};
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api/v1' + path, {...options, headers});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
function busy(id, action) { return async event => { if (event) event.preventDefault(); $(id).disabled = true; notice(''); try { await action(); } catch(e) { notice(e.message); } finally { $(id).disabled = false; } }; }
async function refresh() {
  const data = await api('/documents'); $('documents').replaceChildren();
  for (const d of data.documents) $('documents').append(node('div', `${d.title} · ${d.status} · ${d.chunk_count} 分块`, 'doc'));
  if (!data.documents.length) $('documents').append(node('p', '知识库为空', 'muted'));
}
async function health() {
  const r = await fetch('/health/ready'); const d = await r.json();
  $('mode').textContent = `${d.llm_is_mock ? 'LLM 测试替身' : '真实 LLM · ' + d.providers.llm} / ` +
    `${d.retrieval_is_mock === false ? '真实检索模型' : '检索模型测试替身'} / Qdrant ${d.qdrant_backend || d.mode}`;
  $('health').textContent = d.ready ? '服务就绪' : '依赖未就绪';
}
function renderReport(report) {
  const root = $('results'); root.replaceChildren(node('h2', report.title), node('p', report.conclusion));
  for (const [title, findings] of [['研究发现', report.findings], ['证据分歧', report.disagreements]]) {
    if (!findings.length) continue; root.append(node('h3', title));
    for (const f of findings) root.append(node('div', f.text + '\n' + f.citation_ids.join(' · '), 'finding'));
  }
  root.append(node('h3', '局限')); for (const t of report.limitations) root.append(node('p', t, 'muted'));
  root.append(node('h3', '可核查来源'));
  for (const c of report.citations) {
    const item = node('details', undefined, 'citation');
    item.append(node('summary', `${c.source}${c.page ? ' · 第 ' + c.page + ' 页' : ''} · ${c.citation_id}`), node('p', c.quote));
    const source = node('pre', '展开后读取原文…', 'source-text'); item.append(source);
    item.addEventListener('toggle', async () => { if (!item.open || source.dataset.loaded) return; try {
      const text = await api(`/documents/${encodeURIComponent(c.doc_id)}/chunks/${encodeURIComponent(c.chunk_id)}`);
      source.textContent = `规范化文本偏移 ${text.start}–${text.end}\n\n${text.text}`; source.dataset.loaded = '1';
    } catch(e) { source.textContent = e.message; } }); root.append(item);
  }
  const download = node('button', '下载报告 JSON'); download.addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type:'application/json'}));
    const a = node('a'); a.href = url; a.download = 'knowledgeops-report.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }); root.append(download);
}
async function watch(taskId) {
  const generation = ++pollGeneration; activeTask = taskId; cursor = 0; $('events').replaceChildren(); $('resume').hidden = true;
  while (generation === pollGeneration) {
    const [task, batch] = await Promise.all([api('/tasks/' + taskId), api(`/tasks/${taskId}/events?after=${cursor}`)]);
    for (const e of batch.events) $('events').append(node('li', `${new Date(e.at * 1000).toLocaleTimeString()} ${e.type} ${JSON.stringify(e.data)}`));
    cursor = batch.next_after;
    $('task-status').textContent = `${task.status} · LLM ${task.budget.llm_calls} 次 · 工具 ${task.budget.tool_calls} 次 · Token ${task.budget.tokens}${task.budget.estimated ? '（估算）' : ''}`;
    if (task.status === 'succeeded') { if (task.kind === 'research') renderReport(task.result); await refresh(); break; }
    if (['failed','interrupted'].includes(task.status)) { notice(task.error); $('resume').hidden = task.status !== 'interrupted'; break; }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
}
$('connect').onclick = busy('connect', async () => { sessionStorage.setItem('ko-api-key', $('key').value); await refresh(); await health(); });
$('refresh').onclick = busy('refresh', refresh);
$('upload').onsubmit = async e => { e.preventDefault(); const data = new FormData(); if (!$('file').files.length) return; data.append('file', $('file').files[0]);
  try { const task = await api('/documents', {method:'POST',body:data}); await watch(task.task_id); } catch(e) { notice(e.message); } };
$('url-form').onsubmit = async e => { e.preventDefault(); try { const task = await api('/documents/url', {method:'POST', body:JSON.stringify({url:$('url').value})}); await watch(task.task_id); } catch(e) { notice(e.message); } };
$('search').onclick = busy('search', async () => {
  const result = await api('/query', {method:'POST', body:JSON.stringify({query:$('question').value, mode:$('retrieval').value, rerank:$('rerank').checked})});
  $('results').replaceChildren(node('h2', `检索结果 · ${result.elapsed_ms.toFixed(1)} ms`));
  for (const warning of result.warnings) $('results').append(node('p', warning, 'muted'));
  for (const h of result.hits) { const card = node('div', undefined, 'hit'); card.append(node('strong', `${h.chunk.title} · 页码 ${h.chunk.page || '—'}`), node('p', h.chunk.text), node('p', JSON.stringify({...h,chunk:undefined}), 'scores')); $('results').append(card); }
  if (!result.hits.length) $('results').append(node('p', '没有找到证据。'));
});
$('research').onclick = busy('research', async () => {
  const task = await api('/research', {method:'POST', body:JSON.stringify({question:$('question').value, session_id:session})});
  session = task.session_id; $('session').textContent = session; await watch(task.task_id);
});
$('new-session').onclick = () => { session = null; $('session').textContent = '新会话'; notice(''); };
$('resume').onclick = busy('resume', async () => { await api(`/tasks/${activeTask}/resume`, {method:'POST'}); await watch(activeTask); });
health().catch(e => notice(e.message));
