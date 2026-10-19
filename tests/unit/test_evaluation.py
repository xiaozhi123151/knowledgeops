import pytest

from scripts.evaluate_retrieval import document_ranking, metrics


def test_retrieval_metric_reference_values():
    ranking = ['noise','relevant-b','relevant-a']
    scores = metrics(ranking,{'relevant-a','relevant-b'})
    assert scores['recall@1'] == 0
    assert scores['recall@5'] == 1
    assert scores['mrr@10'] == .5
    assert metrics([],{'missing'})['mrr@10'] == 0
    with pytest.raises(ValueError,match='QRELS_EMPTY'):
        metrics([],set())


def test_document_collapse_preserves_rank():
    assert document_ranking([{'chunk':{'doc_id':x}} for x in ['a','a','b','a','c']]) == ['a','b','c']


def test_worker_heartbeat_freshness(settings):
    from knowledgeops.storage.db import Database
    from knowledgeops.storage.tasks import TaskStore
    store = TaskStore(Database(settings.data_dir),settings)
    assert not store.worker_ready()
    store.worker_heartbeat()
    assert store.worker_ready()
    with store.db.connect() as c:
        c.execute("UPDATE meta SET value='0' WHERE key='worker_heartbeat'")
    assert not store.worker_ready()
