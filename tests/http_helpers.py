import time


def wait_task(client, task_id):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        task = client.get('/api/v1/tasks/' + task_id).json()
        if task['status'] in ('succeeded', 'failed'):
            assert task['status'] == 'succeeded', task.get('error')
            return task
        time.sleep(.05)
    raise AssertionError('task did not finish')
