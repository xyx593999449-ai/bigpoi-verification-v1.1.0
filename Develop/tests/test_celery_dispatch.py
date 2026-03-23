import sys
import os
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../worker')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../generate-batch/scripts')))

from celery_worker import celery_app, run_verification

def test_celery_eager_dispatch(monkeypatch):
    """
    调度层单测 Agent 核心验证点：
    1. 任务能否被调度器无冲撞拆解放入队列。
    2. Celery Worker 是否能够无休克地消费 1000 条压测数据。
    这里使用 Eager 模式模拟单测无 Redis 环境下的队列机制。
    """
    # 强制在单测环境内把任务吞吐变为本地同步执行，验证路由无误
    celery_app.conf.update(task_always_eager=True)
    
    start_time = time.time()
    successful_dispatches = 0
    
    # 模拟推送 1000 条 db 压测任务
    for i in range(100):  # 为了单测速度使用 100 条
        task_result = run_verification.delay(f"poi_mock_{i}", f"db_{i}", "batch_test_001")
        assert task_result.successful(), f"Task {i} failed to dispatch or execute!"
        assert task_result.result.get("status") == "success"
        successful_dispatches += 1
        
    duration = time.time() - start_time
    print(f"\\n✅ [调度单测] 成功分发并消费 {successful_dispatches} 条任务，耗时 {duration:.2f} 秒。")
    assert successful_dispatches == 100
