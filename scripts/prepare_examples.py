"""Create owned, deterministic bilingual fixtures; never read surrounding personal files."""
import io
import json
from pathlib import Path

DOCUMENTS = {
 'redis_aof.md': '# Redis AOF\n\nAOF (Append Only File) records Redis write commands. The appendfsync everysec policy can lose about one second of writes after a crash. AOF rewrite compacts the log.\n\nRedis 的 AOF 追加日志记录写命令。每秒刷盘策略在崩溃时可能丢失约一秒写入，重写用于压缩日志。',
 'redis_rdb.md': '# Redis RDB\n\nRDB creates point-in-time snapshots. Data written after the last completed snapshot can be lost. RDB is useful for compact backups and fast loading.\n\nRedis 的 RDB 保存时间点快照，最后一次快照之后的数据存在丢失风险，适合紧凑备份。',
 'qdrant.md': '# Qdrant vectors\n\nQdrant stores dense vectors and payload metadata. Cosine similarity measures vector direction. The embedding dimension must match the collection configuration.\n\nQdrant 向量数据库支持稠密向量、余弦相似度和来源元数据过滤，向量维度必须匹配集合。',
 'bm25.md': '# BM25 lexical retrieval\n\nBM25 ranks documents using term frequency, inverse document frequency and length normalization. Chinese text needs segmentation. Zero or negative IDF can occur in small corpora.\n\nBM25 关键词检索依赖词频、逆文档频率和长度归一化。中文需要分词，小语料中的 IDF 可能为零或负数。',
 'rrf.md': '# Reciprocal Rank Fusion\n\nRRF merges ranked lists with score sum(1/(k+rank)). KnowledgeOps uses k=60. RRF does not directly add incompatible dense and BM25 raw scores.\n\nRRF 倒数排名融合使用排名而非直接相加原始得分，常数 k 默认等于 60。',
 'reranker.md': '# CrossEncoder reranking\n\nA CrossEncoder jointly processes a query and a candidate passage to predict relevance. It reranks an existing candidate set; it cannot recover documents absent from that set.\n\nCrossEncoder 交叉编码器联合编码问题与候选段落进行重排，无法召回候选集合之外的文档。',
 'langgraph.md': '# LangGraph persistence\n\nLangGraph checkpoints graph state at execution boundaries. A stable thread_id identifies a run. Recovery also needs idempotent external operations and persisted budgets.\n\nLangGraph 检查点支持状态持久化和中断恢复，外部副作用仍需幂等处理，预算不能在恢复时重置。',
 'harness.md': '# Agent Harness\n\nThe Harness limits execution steps, tool attempts, model calls and token budgets. Timeouts and bounded retries prevent uncontrolled loops. SDK implicit retries must be disabled when the application owns retry accounting.\n\nAgent 执行护栏限制步数、工具次数、模型调用和 Token 预算，超时和有限重试避免无限循环。',
 'ingestion.md': '# Document ingestion\n\nRaw SHA-256 hashes support integrity checking. Normalized text defines document identity. PDF page numbers and chunk offsets make source passages inspectable. Scan-only PDFs need OCR.\n\n知识导入保存原文件哈希、规范化文本、PDF 页码和分块偏移。扫描 PDF 需要 OCR。',
 'security.md': '# Safe web import\n\nWeb import accepts only public HTTP and HTTPS pages. Validate every redirect, reject private addresses, and pin connections to validated IPs to prevent DNS rebinding. Agent tools must be allowlisted.\n\n网页导入阻断私网与云元数据地址，逐次校验重定向并绑定已验证 IP。工具白名单不包含任意 Shell。',
 'observability.md': '# Observability\n\nLocal task events are durable. Optional Langfuse exports operational metadata without prompts or source text by default. A tracing outage must not stop research tasks.\n\n可观测性以本地持久事件为准，Langfuse 可选，追踪服务故障不应阻断研究。',
 'metrics.txt': 'Retrieval evaluation uses relevance judgments. Recall@K is the fraction of relevant documents in the first K results. MRR@10 uses the reciprocal rank of the first relevant document up to rank ten. P50 and P95 summarize query latency.\n\n召回评测需要相关性标注。Recall 衡量相关文档覆盖，MRR 衡量首个相关结果排名，P50 和 P95 衡量延迟分位数。',
}
QUESTIONS = [
 ('redis_aof.md', 'What does Redis AOF record?'), ('redis_aof.md', 'Redis AOF 每秒刷盘可能丢失多少写入？'), ('redis_aof.md', 'How does AOF rewrite compact the log?'),
 ('redis_rdb.md', 'What are Redis RDB snapshots?'), ('redis_rdb.md', 'RDB 快照之后的数据有什么丢失风险？'), ('redis_rdb.md', 'Why use RDB for compact backups?'),
 ('qdrant.md', 'How does Qdrant store dense vectors?'), ('qdrant.md', 'Qdrant 集合向量维度为什么必须匹配？'), ('qdrant.md', 'What does cosine similarity measure in Qdrant?'),
 ('bm25.md', 'Which frequency signals does BM25 use?'), ('bm25.md', 'BM25 中文关键词检索为什么需要分词？'), ('bm25.md', 'Can BM25 inverse document frequency be negative?'),
 ('rrf.md', 'What formula does RRF use?'), ('rrf.md', 'RRF 倒数排名融合的 k 默认是多少？'), ('rrf.md', 'Does RRF add raw dense and BM25 scores?'),
 ('reranker.md', 'How does a CrossEncoder rerank candidates?'), ('reranker.md', '交叉编码器能召回候选集合之外的文档吗？'), ('reranker.md', 'What inputs does CrossEncoder process jointly?'),
 ('langgraph.md', 'What state does LangGraph checkpoint?'), ('langgraph.md', 'LangGraph 中断恢复为什么还需要幂等？'), ('langgraph.md', 'Why does LangGraph recovery need a stable thread_id?'),
 ('harness.md', 'Which budgets does Agent Harness enforce?'), ('harness.md', '执行护栏如何通过超时与有限重试避免无限循环？'), ('harness.md', 'Why disable SDK implicit retries for Harness accounting?'),
 ('ingestion.md', 'How do PDF page numbers and offsets support citations?'), ('ingestion.md', '扫描 PDF 为什么需要 OCR？'),
 ('security.md', 'How does pinned web import prevent DNS rebinding?'), ('security.md', '网页导入为什么阻断私网和云元数据地址？'),
 ('observability.md', 'Should a Langfuse tracing outage stop research?'), ('metrics.txt', 'How are Recall@K MRR@10 P50 and P95 defined?'),
]


def make_pdf():
    # Dev dependency only; the generated fixture is committed so smoke needs no PDF-generation library.
    from reportlab.pdfgen import canvas
    output = io.BytesIO()
    pdf = canvas.Canvas(output, invariant=1)
    pdf.drawString(40, 720, 'Redis AOF persistence records every write command.')
    pdf.drawString(40, 700, 'RDB creates periodic snapshots for backups.')
    pdf.showPage()
    pdf.drawString(40, 720, 'Qdrant stores dense vectors and metadata.')
    pdf.save()
    return output.getvalue()


def make_chinese_pdf():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    output = io.BytesIO()
    pdf = canvas.Canvas(output, invariant=1)
    pdf.setFont('STSong-Light', 12)
    pdf.drawString(40, 720, '中文知识库支持混合检索、证据引用和任务恢复。')
    pdf.drawString(40, 700, 'CrossEncoder 对候选段落进行重排。')
    pdf.save()
    return output.getvalue()


def main():
    root = Path(__file__).parents[1] / 'examples'
    corpus = root / 'corpus'
    corpus.mkdir(parents=True, exist_ok=True)
    for filename, text in DOCUMENTS.items():
        (corpus / filename).write_text(text, encoding='utf-8')
    with (root / 'queries.jsonl').open('w', encoding='utf-8') as f:
        for i, (source, question) in enumerate(QUESTIONS, 1):
            f.write(json.dumps({'id':f'q{i:02}', 'query':question, 'relevant_sources':[source]}, ensure_ascii=False)+'\n')
    (root / 'sample.pdf').write_bytes(make_pdf())
    (root / 'sample-zh.pdf').write_bytes(make_chinese_pdf())
    (root / 'sample.html').write_text('<html><main><h1>KnowledgeOps sample</h1><p>Evidence needs inspectable sources.</p></main></html>', encoding='utf-8')
    print(f'Wrote {len(DOCUMENTS)} owned documents and {len(QUESTIONS)} labeled queries.')


if __name__ == '__main__':
    main()
