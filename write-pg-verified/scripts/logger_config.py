#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志配置模块
提供统一的日志配置和获取方法
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


def setup_logger(
    name: str = 'write_pg_verified',
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_dir: Optional[str] = None
) -> logging.Logger:
    """
    设置并返回一个配置好的日志记录器

    Args:
        name: 日志记录器名称
        level: 日志级别 (logging.DEBUG, logging.INFO, etc.)
        log_file: 日志文件名（不含路径）
        log_dir: 日志目录路径，默认为项目根目录下的 logs 文件夹

    Returns:
        配置好的 Logger 对象
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 创建日志格式
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器（可选）
    if log_file:
        if log_dir is None:
            # 默认使用项目根目录下的 logs 文件夹
            project_root = Path(__file__).parent.parent.parent.parent.parent.parent
            log_dir = project_root / 'logs'
        else:
            log_dir = Path(log_dir)

        # 确保日志目录存在
        log_dir.mkdir(parents=True, exist_ok=True)

        log_path = log_dir / log_file

        # 使用追加模式，每天一个文件
        file_handler = logging.FileHandler(
            log_path,
            mode='a',
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = 'write_pg_verified') -> logging.Logger:
    """
    获取已配置的日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        Logger 对象
    """
    return logging.getLogger(name)


# 预配置的日志记录器实例
logger = setup_logger()
