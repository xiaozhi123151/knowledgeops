"""Authored, inspectable questions. Freeze BEFORE running retrieval; no model-generated qrels."""

import hashlib
import json

from scripts.common import write_json
from scripts.fetch_benchmark_docs import CORPUS

# source, exact original anchor, keyword question, independently worded semantic question.
FACTS = [
    (
        "python-3.8",
        "There is new syntax ``:=``",
        "Python 3.8 的 := 运算符做什么？",
        "哪个 3.8 语法能在较大表达式中同时给变量赋值？",
    ),
    (
        "python-3.8",
        "There is a new function parameter syntax ``/``",
        "Python 3.8 函数参数中的 / 表示什么？",
        "怎样在 3.8 中禁止调用方用关键字传递部分参数？",
    ),
    (
        "python-3.8",
        'The "vectorcall" protocol is added',
        "Python 3.8 新增哪个 C API 调用协议？",
        "3.8 用什么协议降低 Python 对象调用开销？",
    ),
    (
        "python-3.8",
        "October 14th, 2019",
        "Python 3.8 的发布日期是什么？",
        "2019 年秋季发布的 3.8 正式版是哪一天？",
    ),
    (
        "python-3.9",
        "IANA time zone database",
        "Python 3.9 的 zoneinfo 支持什么数据库？",
        "3.9 标准库如何表示具有地区夏令时规则的时区？",
    ),
    (
        "python-3.9",
        "Dictionary Merge & Update Operators",
        "Python 3.9 引入哪些字典合并操作？",
        "怎样在 3.9 中用运算符组合两个映射？",
    ),
    (
        "python-3.9",
        "removeprefix",
        "Python 3.9 有哪些删除字符串前后缀的方法？",
        "不想把前缀当作字符集合删掉，3.9 有什么精确删除办法？",
    ),
    (
        "python-3.9",
        "Type Hinting Generics",
        "Python 3.9 对内置集合泛型注解有什么改进？",
        "哪个 3.9 改动允许直接给内置容器写元素类型？",
    ),
    (
        "python-3.10",
        "Require OpenSSL 1.1.1 or newer",
        "Python 3.10 要求的 OpenSSL 最低版本？",
        "升级 3.10 后，加密库的最低兼容基线是什么？",
    ),
    (
        "python-3.10",
        "Structural Pattern Matching: Specification",
        "Python 3.10 的 PEP 634 是什么？",
        "哪个 3.10 语言特性能按对象结构分支而不仅是逐个布尔比较？",
    ),
    (
        "python-3.10",
        "Allow writing union types as X | Y",
        "Python 3.10 联合类型的新写法是什么？",
        "3.10 如何用竖线声明值可属于两种类型之一？",
    ),
    (
        "python-3.10",
        "Add Optional Length-Checking To zip",
        "Python 3.10 zip 新增什么长度检查能力？",
        "3.10 如何让配对迭代在输入长度不一致时暴露问题？",
    ),
    (
        "python-3.11",
        "between 10-60% faster",
        "Python 3.11 相比 3.10 官方摘要给出的加速范围？",
        "官方 3.11 发布摘要报告了怎样的性能区间，而非保证每个程序都一样快？",
    ),
    (
        "python-3.11",
        "Support for parsing `TOML",
        "Python 3.11 新增哪个 TOML 解析模块？",
        "3.11 不安装额外依赖时怎样读取 TOML 格式？",
    ),
    (
        "python-3.11",
        "The builtin types :exc:`ExceptionGroup`",
        "Python 3.11 新增的异常组类型是什么？",
        "3.11 如何将多个不相关异常一起包装并处理？",
    ),
    (
        "python-3.11",
        "Added the :class:`~asyncio.TaskGroup` class",
        "Python 3.11 asyncio 新增哪个任务组 API？",
        "哪个 3.11 并发结构帮助等待一组关联协程完成？",
    ),
    ("python-3.12", "October 2, 2023", "Python 3.12 发布日期？", "2023 年推出的 3.12 正式版是哪一天发布的？"),
    (
        "python-3.12",
        "package has been removed from the standard library",
        "Python 3.12 对 distutils 做了什么？",
        "为什么升级 3.12 后不能再假定标准库自带旧构建工具包？",
    ),
    (
        "python-3.12",
        "PEP 695: Type Parameter Syntax",
        "Python 3.12 PEP 695 引入什么语法？",
        "3.12 为泛型声明和类型别名提供了什么新的表达方式？",
    ),
    (
        "python-3.12",
        "sub-interpreters may now be created with a unique GIL per interpreter",
        "Python 3.12 PEP 684 的 GIL 隔离粒度？",
        "3.12 如何让不同子解释器各自拥有解释器锁？",
    ),
    ("python-3.13", "October 7, 2024", "Python 3.13 发布日期？", "2024 年秋季的 3.13 正式版在哪一天发布？"),
    (
        "python-3.13",
        "CPython 3.13 has experimental support",
        "Python 3.13 无 GIL 支持属于什么成熟度？",
        "3.13 是否已把无解释器锁执行作为全面稳定的默认模式？",
    ),
    (
        "python-3.13",
        "It is currently disabled by default",
        "Python 3.13 的基本 JIT 默认是否启用？",
        "安装 3.13 就会自动开启即时编译器吗？",
    ),
    (
        "python-3.13",
        "will cause the GIL to be enabled",
        "Python 3.13 导入未声明 free-threading 支持的扩展可能发生什么？",
        "为什么无锁构建在导入旧 C 扩展后可能又恢复解释器锁？",
    ),
    (
        "asyncio-queue",
        "A first in, first out (FIFO) queue.",
        "asyncio.Queue 按什么顺序取出项目？",
        "异步队列默认先处理最早还是最近加入的项目？",
    ),
    (
        "asyncio-queue",
        "queue size is\n   infinite",
        "asyncio.Queue 的 maxsize 小于等于零意味着什么？",
        "如何配置异步队列使其容量不受正数上限限制？",
    ),
    (
        "asyncio-queue",
        "Raises :exc:`ValueError` if called more times",
        "asyncio.Queue.task_done 调用次数过多会怎样？",
        "消费者把完成通知多发几次时，队列用什么错误揭示计数问题？",
    ),
    (
        "asyncio-queue",
        "methods of asyncio queues don't have a *timeout* parameter",
        "asyncio.Queue 操作如何设置超时？",
        "异步队列不接收等待时长参数时，怎样限制阻塞时间？",
    ),
    (
        "asyncio-sync",
        "Acquiring a lock is *fair*",
        "asyncio.Lock 获取顺序是否公平？",
        "多个协程争抢同一把异步锁时，谁应最先获得锁？",
    ),
    (
        "asyncio-sync",
        "If the lock is *unlocked*, a :exc:`RuntimeError` is raised",
        "asyncio.Lock 在未锁定时 release 会怎样？",
        "重复释放一把已打开的异步锁会触发什么错误？",
    ),
    (
        "asyncio-sync",
        "The flag is set to *false* initially",
        "asyncio.Event 的初始标志是什么？",
        "尚未调用 set 时，异步事件是否已经处于通知状态？",
    ),
    (
        "asyncio-sync",
        "asyncio primitives are not thread-safe",
        "asyncio 同步原语可用于 OS 线程同步吗？",
        "能否让不同操作系统线程安全地共享这些协程锁？",
    ),
    (
        "asyncio-task",
        "the remaining tasks in the group are cancelled",
        "TaskGroup 子任务失败后其余任务怎样处理？",
        "一个关联子协程出错时，结构化任务组会如何处置兄弟任务？",
    ),
    (
        "asyncio-task",
        "**won't be cancelled** and will continue to run",
        "asyncio.gather 默认遇到首个异常会取消其他任务吗？",
        "聚合等待中的一个协程失败后，其他协程默认还会继续运行吗？",
    ),
    (
        "asyncio-task",
        "The function will wait until the future is actually cancelled",
        "asyncio.wait_for 的实际等待能否超过 timeout？",
        "为什么给异步任务设置等待上限后，真正返回仍可能更晚？",
    ),
    (
        "asyncio-task",
        "Task running in ``something()`` is not cancelled",
        "asyncio.shield 如何影响外部取消？",
        "怎样让内部协程不随外层等待者一起被取消？",
    ),
    (
        "asyncio-stream",
        "64 KiB",
        "asyncio 流读取器默认缓冲限制是多少？",
        "未显式指定流读取缓冲大小时，官方文档给出的容量是多少？",
    ),
    (
        "asyncio-stream",
        "backlog=100",
        "asyncio.start_server 默认 backlog 值？",
        "异步 TCP 服务的默认待接受连接队列参数是多少？",
    ),
    (
        "asyncio-subprocess",
        "This method can deadlock",
        "asyncio 子进程在管道输出时直接 wait 有何风险？",
        "为什么子进程写满输出管道后，单纯等待进程退出可能永远卡住？",
    ),
    (
        "concurrent.futures",
        "*chunksize* has no effect",
        "ThreadPoolExecutor.map 的 chunksize 有效果吗？",
        "把线程池映射的分块参数调大，会像进程池一样改变任务批量吗？",
    ),
]

CROSS = [
    (24, 28, "异步队列与异步锁分别提供怎样的取出顺序与等待公平性？"),
    (27, 31, "异步队列和同步原语在超时参数与 OS 线程使用上各有什么限制？"),
    (32, 33, "对比 TaskGroup 与 gather：一个任务失败后其他任务会被取消吗？"),
    (34, 35, "对比 wait_for 和 shield 对任务取消与等待时间的影响。"),
    (38, 39, "对比异步子进程等待风险与线程池 map 分块参数的限制。"),
    (26, 29, "对比队列完成计数溢出与释放未持有异步锁时的异常类型。"),
    (36, 37, "异步 TCP 流的默认缓冲容量和服务器 backlog 分别是什么？"),
    (14, 32, "Python 3.11 的异常组与 TaskGroup 失败处理怎样联系起来？"),
    (15, 32, "结合 3.11 发布说明与任务文档解释新增任务组及其失败语义。"),
    (30, 24, "异步 Event 的初始状态与 Queue 的默认取出顺序分别是什么？"),
]
VERSIONS = [
    (19, 21, "比较 Python 3.12 每子解释器 GIL 与 3.13 实验性 free-threading，两者是否同一能力？"),
    (10, 18, "比较 Python 3.10 联合类型竖线写法与 3.12 泛型类型参数语法。"),
    (8, 17, "从 3.10 到 3.12，OpenSSL 最低要求与 distutils 的移除分别是什么变化？"),
    (16, 20, "比较 Python 3.12 与 3.13 的正式发布日期。"),
    (12, 22, "能否把 Python 3.11 性能摘要与 3.13 默认关闭的 JIT 当成同一项保证？"),
    (13, 17, "比较 Python 3.11 标准库新增的 TOML 解析能力与 3.12 移除的构建包。"),
    (0, 9, "比较 Python 3.8 赋值表达式与 3.10 结构化模式匹配，分别解决什么问题？"),
    (7, 18, "比较 Python 3.9 内置集合泛型注解与 3.12 类型参数语法。"),
    (2, 22, "比较 Python 3.8 vectorcall 与 3.13 JIT 的作用和默认启用情况。"),
    (19, 23, "比较 3.12 子解释器锁隔离与 3.13 旧扩展导致重新启用 GIL 的条件。"),
]
UNKNOWN = [
    "Python 3.13 在 RTX 5060 上运行我的私有 Web 服务的准确 QPS 是多少？",
    "Python 3.12 在我的生产数据库上相对 3.11 提速多少百分比？",
    "DeepSeek V2、V3、V4.1 在单张 A100 80GB batch=1 的绝对 tokens/s 排名？",
    "DeepSeek V4.1 对我公司内部保密合同问答的准确率是多少？",
    "BGE-M3 在这个项目 2030 年的实测 nDCG 是多少？",
    "Redis 9.9 在 KnowledgeOps 私有集群上的实测 P99 是多少？",
    "Python 3.13 在我的付费客户流量上能节省多少云费用？",
    "这批文档是否给出我的服务器下周会发生的内存泄漏时间？",
    "asyncio.Lock 在我公司的业务里每秒准确可获取多少次？",
    "给定未提供的 CPU 和网络，asyncio.Queue 的最大真实吞吐量是多少？",
    "DeepSeek 的未公开训练数据中包含我公司的哪些用户邮件？",
    "Python 3.14 在我内部测试集上的性能相对 3.13 具体提升率？",
    "KnowledgeOps 未来两年的精确维护成本和盈利是多少？",
    "ThreadPoolExecutor 在我未公开代码上的最优 worker 数是多少？",
    "我的私有金融模型用 TaskGroup 后精确收益率是多少？",
    "能从这些公开文档确认我的 GitHub 私有仓库访问密钥吗？",
    "Python 3.12 对尚未提供的业务 bug 的根因是什么？",
    "DeepSeek V4.1 本次部署每小时真实耗电多少千瓦时？",
    "异步 TCP 流在我的家庭宽带上当前丢包率的精确数值？",
    "Qdrant 在本项目五千万私有分块上的实际检索 P95 是多少？",
]


def main():
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    sources = {s["id"]: s for s in manifest["sources"]}
    evidence = []
    for i, (source, needle, _, _) in enumerate(FACTS):
        text = (CORPUS / "documents" / sources[source]["filename"]).read_text(encoding="utf-8")
        start = text.index(needle)  # Fail loudly on any changed/mistyped evidence.
        # Preserve exact original anchor; context is independently inspectable in the source snapshot.
        evidence.append(
            {
                "id": f"F{i + 1:02}",
                "source_id": source,
                "quote": needle,
                "line": text[:start].count("\n") + 1,
                "start": start,
                "end": start + len(needle),
                "context": text[max(0, start - 200) : min(len(text), start + len(needle) + 300)],
            }
        )
    rows = []

    def add(category, question, refs):
        rows.append(
            {
                "id": f"Q{len(rows) + 1:03}",
                "category": category,
                "question": question,
                "evidence_ids": [evidence[i]["id"] for i in refs],
                "answerable": bool(refs),
            }
        )

    for i, fact in enumerate(FACTS):
        add("keyword", fact[2], [i])
        add("semantic", fact[3], [i])
    for a, b, q in CROSS:
        add("cross_document", q, [a, b])
    for a, b, q in VERSIONS:
        add("version_conflict", q, [a, b])
    for q in UNKNOWN:
        add("unanswerable", q, [])
    result = {
        "schema_version": 1,
        "annotation": "Assistant-authored and mechanically anchor-checked; human review pending. "
        "Incomplete positive judgments, not exhaustively human-labeled negatives.",
        "questions": rows,
        "evidence": evidence,
        "source_hashes": {s["id"]: s["sha256"] for s in sources.values()},
    }
    write_json(CORPUS / "questions.json", result)
    digest = hashlib.sha256((CORPUS / "questions.json").read_bytes()).hexdigest()
    (CORPUS / "questions.sha256").write_text(digest + "\n", encoding="ascii")
    print(f"Frozen {len(rows)} questions, {len(evidence)} anchors: {digest}")


if __name__ == "__main__":
    main()
