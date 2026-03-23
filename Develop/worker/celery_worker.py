#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Celery Worker 节点入口
功能：监听消息队列中的核验任务，触发单个 POI 的上下游 AI 技能（独立解耦）。
"""

import os
import sys
import logging
from celery import Celery

# 获取项目根目录以引入其他模块
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

# 配置 Celery
BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
BACKEND_URL = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')

celery_app = Celery('bigpoi_tasks', broker=BROKER_URL, backend=BACKEND_URL)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    worker_prefetch_multiplier=1, # 强一致公平调度
    task_acks_late=True           # 执行完才确认防止丢失
)

@celery_app.task(name='celery_worker.run_verification', bind=True, max_retries=3)
def run_verification(self, poi_id: str, db_id: str, batch_id: str):
    """
    Sub-Agent 1 (Worker): 接收调度层派发的单一 POI 核验任务
    """
    logger = run_verification.get_logger()
    logger.info(f"========== 收到任务 | POI: {poi_id} | Batch: {batch_id} | DB_ID: {db_id} ==========")
    
    try:
        # TODO: 在此处拉起 `skills-bigpoi-verification` 父技能逻辑
        # 1. （通过数据库配置）读取当前 db_id 连接提取该 POI input 数据
        # 2. 调用 init_run_context.py 并创建沙箱 run_id
        # 3. 阻塞等待：evidence-collection -> verification -> qc
        # 当前仅保留 Sub-Agent 1 的入口壳子，后续阶段由联调 Agent 贯通
        
        logger.info(f"POI: {poi_id} 模拟执行完成该路分支任务派发。")
        return {"status": "success", "poi_id": poi_id}
        
    except Exception as e:
        logger.error(f"POI: {poi_id} 执行出错: {str(e)}")
        # 遇到临界崩溃时按阶梯延迟重试
        raise self.retry(exc=e, countdown=60)

if __name__ == '__main__':
    # 允许直接启动 worker 测试
    celery_app.worker_main(['worker', '--loglevel=info', '--pool=solo'])
