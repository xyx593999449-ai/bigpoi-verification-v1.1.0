#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批次生成脚本 (Generate Batch Script)
功能：从源表选取指定条件的数据插入目标表，并生成批次号
"""

import psycopg2
import csv
import os
import sys
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from celery import Celery

# 基础 Celery App，用于推任务
BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
celery_app = Celery('bigpoi_tasks', broker=BROKER_URL)

# 配置日志目录（在脚本的外层目录下）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
LOG_DIR = os.path.join(PARENT_DIR, 'tmp')
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# log_file 将在获取 worker_id 后动态设置
log_file = None

# 设置控制台输出为UTF-8编码（Windows兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 初始化日志（先只用控制台输出）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def setup_file_logging(worker_id: str):
    """设置文件日志处理器"""
    global log_file, logger

    # 移除旧的文件处理器
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)

    # 构建 log 文件名（包含 worker_id）
    log_file = os.path.join(LOG_DIR, f'generate_batch_worker_{worker_id}.log')

    # 添加新的文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)


class BatchGenerator:
    """批次生成器类"""

    def __init__(self, db_map_path: str, table_map_path: str, worker_id: str = None):
        """
        初始化批次生成器

        Args:
            db_map_path: database_map.csv 文件路径
            table_map_path: skill_table_map.csv 文件路径
            worker_id: 工作进程ID（可选）
        """
        self.db_map_path = db_map_path
        self.table_map_path = table_map_path
        self.db_connections: Dict[str, Dict] = {}
        self.table_mappings: Dict[str, Dict] = {}
        self.worker_id = worker_id

        logger.info("=" * 80)
        logger.info("批次生成器初始化")
        if worker_id:
            logger.info(f"Worker ID: {worker_id}")
        logger.info("=" * 80)

    def load_database_config(self) -> bool:
        """
        加载数据库配置信息

        Returns:
            bool: 加载是否成功
        """
        logger.info(f"[步骤1] 开始加载数据库配置: {self.db_map_path}")

        if not os.path.exists(self.db_map_path):
            logger.error(f"数据库配置文件不存在: {self.db_map_path}")
            return False

        try:
            with open(self.db_map_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    db_id = row['id']
                    self.db_connections[db_id] = {
                        'ip': row['ip'],
                        'port': int(row['port']),
                        'db': row['db'],
                        'user': row['user'],
                        'password': row['password']
                    }
                    logger.info(f"  ✓ 加载数据库配置成功: {db_id} -> {row['ip']}:{row['port']}/{row['db']}")

            logger.info(f"[步骤1] 数据库配置加载完成，共加载 {len(self.db_connections)} 个数据库配置")
            return True

        except Exception as e:
            logger.error(f"[步骤1] 加载数据库配置失败: {str(e)}")
            return False

    def load_table_mapping(self) -> bool:
        """
        加载技能表映射配置

        Returns:
            bool: 加载是否成功
        """
        logger.info(f"[步骤2] 开始加载技能表映射配置: {self.table_map_path}")

        if not os.path.exists(self.table_map_path):
            logger.error(f"技能表映射配置文件不存在: {self.table_map_path}")
            return False

        try:
            with open(self.table_map_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    skill_name = row['skill_name']
                    self.table_mappings[skill_name] = {
                        'input_table_name': row['input_table_name'],
                        'input_table_flds': row['input_table_flds'],
                        'select_condition': row['select_condition'],
                        'select_limit': int(row['select_limit']),
                        'update_condition': row['update_condition'],
                        'output_table_name': row['output_table_name'],
                        'batch_table_name': row.get('batch_table_name', '').strip()
                    }
                    logger.info(f"  ✓ 加载技能映射配置成功: {skill_name}")
                    logger.info(f"    - 输入表: {row['input_table_name']}")
                    logger.info(f"    - 输出表: {row['output_table_name']}")
                    logger.info(f"    - 限制条数: {row['select_limit']}")

            logger.info(f"[步骤2] 技能表映射配置加载完成，共加载 {len(self.table_mappings)} 个技能配置")
            return True

        except Exception as e:
            logger.error(f"[步骤2] 加载技能表映射配置失败: {str(e)}")
            return False

    def get_db_connection(self, db_id: str) -> Optional[psycopg2.extensions.connection]:
        """
        获取数据库连接

        Args:
            db_id: 数据库ID

        Returns:
            数据库连接对象，失败返回None
        """
        if db_id not in self.db_connections:
            logger.error(f"数据库ID不存在: {db_id}")
            return None

        config = self.db_connections[db_id]
        logger.info(f"[步骤3] 尝试连接数据库: {db_id} ({config['ip']}:{config['port']}/{config['db']})")

        try:
            from psycopg2.extras import RealDictCursor
            # 使用标准游标，不使用 RealDictCursor
            conn = psycopg2.connect(
                host=config['ip'],
                port=config['port'],
                database=config['db'],
                user=config['user'],
                password=config['password']
            )
            # 设置为使用标准游标（返回元组）
            conn.cursor_factory = None
            logger.info(f"[步骤3] 数据库连接成功: {db_id}")
            return conn

        except Exception as e:
            logger.error(f"[步骤3] 数据库连接失败: {db_id} - {str(e)}")
            return None

    def parse_input_fields(self, fields_str: str) -> List[str]:
        """
        解析输入字段字符串

        Args:
            fields_str: 逗号分隔的字段字符串

        Returns:
            字段列表
        """
        # 移除首尾引号，按逗号分割
        fields_str = fields_str.strip()
        if fields_str.startswith('"') and fields_str.endswith('"'):
            fields_str = fields_str[1:-1]
        elif fields_str.startswith("'") and fields_str.endswith("'"):
            fields_str = fields_str[1:-1]

        fields = [f.strip() for f in fields_str.split(',')]
        return fields

    def generate_batch_id(self, worker_id: str) -> str:
        """
        生成批次号

        Args:
            worker_id: 工作进程ID（雪花算法生成的唯一标识）

        Returns:
            批次号字符串，格式: BATCH_YYYYMMDD_HH_MM_SS_workerId
        """
        now = datetime.now()
        batch_id = f"BATCH_{now.strftime('%Y%m%d_%H_%M_%S')}_{worker_id}"
        logger.info(f"[步骤4] 生成批次号: {batch_id}")
        return batch_id

    def check_table_exists(self, conn: psycopg2.extensions.connection, table_name: str) -> bool:
        """
        检查表是否存在

        Args:
            conn: 数据库连接
            table_name: 表名（包含schema）

        Returns:
            表是否存在
        """
        logger.info(f"[步骤5] 检查表是否存在: {table_name}")

        try:
            # 解析schema和表名
            parts = table_name.split('.')
            if len(parts) == 2:
                schema_name, table = parts[0], parts[1]
            else:
                schema_name = 'public'
                table = parts[0]

            cursor = conn.cursor()
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
            """, (schema_name, table))
            exists = cursor.fetchone()[0]
            cursor.close()

            if exists:
                logger.info(f"[步骤5] 表存在: {table_name}")
            else:
                logger.error(f"[步骤5] 表不存在: {table_name}")

            return exists

        except Exception as e:
            logger.error(f"[步骤5] 检查表存在性失败: {str(e)}")
            return False

    def execute_batch_generation(
        self,
        db_id: str,
        skill_name: str,
        worker_id: str
    ) -> Tuple[bool, str, int]:
        """
        执行批次生成

        Args:
            db_id: 数据库ID
            skill_name: 技能名称
            worker_id: 工作进程ID（雪花算法生成的唯一标识，必填）

        Returns:
            (是否成功, 批次号, 处理记录数)
        """
        self.worker_id = worker_id
        logger.info("=" * 80)
        logger.info(f"开始执行批次生成: db_id={db_id}, skill_name={skill_name}, worker_id={worker_id}")
        logger.info("=" * 80)

        # 验证参数
        if db_id not in self.db_connections:
            logger.error(f"数据库ID不存在: {db_id}")
            return False, "", 0

        if skill_name not in self.table_mappings:
            logger.error(f"技能名称不存在: {skill_name}")
            return False, "", 0

        mapping = self.table_mappings[skill_name]

        # 获取数据库连接
        conn = self.get_db_connection(db_id)
        if not conn:
            return False, "", 0

        try:
            # 生成批次号（包含 worker_id）
            batch_id = self.generate_batch_id(worker_id)

            # 检查源表和目标表是否存在
            input_table = mapping['input_table_name']
            output_table = mapping['output_table_name']
            batch_table_name = mapping.get('batch_table_name', '').strip()

            if not self.check_table_exists(conn, input_table):
                logger.error(f"源表不存在，终止操作: {input_table}")
                return False, batch_id, 0

            if not self.check_table_exists(conn, output_table):
                logger.error(f"目标表不存在，终止操作: {output_table}")
                return False, batch_id, 0

            # 解析字段
            input_fields = self.parse_input_fields(mapping['input_table_flds'])
            logger.info(f"[步骤6] 解析输入字段: 共 {len(input_fields)} 个字段")
            for i, field in enumerate(input_fields, 1):
                logger.info(f"    {i}. {field}")

            # select_condition 和 update_condition 不替换 {batch_id}，直接使用
            select_condition = mapping['select_condition']
            logger.info(f"[步骤7] 查询条件: {select_condition}")

            # input_table_flds 替换 {batch_id} 为实际批次号（在SELECT部分）
            select_fields = mapping['input_table_flds'].replace('{batch_id}', f"{batch_id}")
            logger.info(f"[步骤8] SELECT字段（已替换批次号）: {select_fields}")

            # 构建 INSERT INTO SELECT 查询（不指定目标表字段列表）
            insert_select_query = f"""
                INSERT INTO {output_table}
                SELECT {select_fields}
                FROM {input_table}
                WHERE {select_condition}
                LIMIT {mapping['select_limit']}
            """
            logger.info(f"[步骤9] 构建INSERT INTO SELECT查询:")
            logger.info(f"    {insert_select_query}")

            # 执行 INSERT INTO SELECT
            cursor = conn.cursor()
            logger.info(f"[步骤10] 执行INSERT INTO SELECT...")
            cursor.execute(insert_select_query)
            inserted_count = cursor.rowcount
            logger.info(f"[步骤10] 数据插入完成，共插入 {inserted_count} 条记录")

            if inserted_count == 0:
                logger.warning("没有插入任何记录，操作结束")
                cursor.close()
                conn.close()
                return True, batch_id, 0

            # 提交事务
            conn.commit()
            logger.info(f"[步骤11] 事务提交成功")

            # 更新源表状态（如果配置了update_condition）
            if mapping['update_condition']:
                # 自动获取源表主键
                logger.info(f"[步骤12] 自动获取源表主键...")

                # 解析schema和表名
                parts = input_table.split('.')
                if len(parts) == 2:
                    schema_name, table_name = parts[0], parts[1]
                else:
                    schema_name, table_name = 'public', parts[0]

                # 查询源表主键
                pk_query = """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    JOIN pg_class c ON c.oid = i.indrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE i.indisprimary = true
                      AND n.nspname = %s
                      AND c.relname = %s
                """
                cursor.execute(pk_query, (schema_name, table_name))
                pk_result = cursor.fetchone()

                if not pk_result:
                    logger.warning(f"未找到源表主键，跳过更新操作")
                else:
                    pk_field = pk_result[0]
                    logger.info(f"    源表主键: {pk_field}")

                    # 先查询源表中被插入记录的主键
                    select_ids_query = f"""
                        SELECT {pk_field}
                        FROM {input_table}
                        WHERE {select_condition}
                        LIMIT {mapping['select_limit']}
                    """
                    logger.info(f"    查询主键: {select_ids_query}")

                    cursor.execute(select_ids_query)
                    source_ids = [row[0] for row in cursor.fetchall()]
                    logger.info(f"    获取到 {len(source_ids)} 个主键")

                    if source_ids:
                        # 使用主键列表进行更新
                        update_condition = mapping['update_condition']
                        update_query = f"""
                            UPDATE {input_table}
                            SET {update_condition}
                            WHERE {pk_field} = ANY(%s)
                        """
                        logger.info(f"    更新查询: {update_query}")

                        cursor.execute(update_query, (source_ids,))
                        updated_count = cursor.rowcount
                        logger.info(f"[步骤12] 源表状态更新完成，共更新 {updated_count} 条记录")

                        # 再次提交事务
                        conn.commit()
                        logger.info(f"[步骤13] 更新事务提交成功")

                    # ===== Sub-Agent 1 改造核心：基于取出的源表主键 IDs 派发异步任务 =====
                    if source_ids:
                        logger.info(f"[Celery 派发] 开始推送 {len(source_ids)} 条任务至队列...")
                        pushed_count = 0
                        for poi_id in source_ids:
                            try:
                                celery_app.send_task(
                                    'celery_worker.run_verification', 
                                    args=[str(poi_id), db_id, batch_id]
                                )
                                pushed_count += 1
                            except Exception as ce:
                                logger.error(f"[Celery 派发] 推送 POI {poi_id} 到消息队列失败: {str(ce)}")
                        
                        logger.info(f"[Celery 派发] 成功将 {pushed_count} 条记录转交异步并发调度。")
                    # ======================================================================

            # 如果配置了批次表，插入批次记录
            if batch_table_name:
                logger.info(f"[步骤14] 插入批次记录到批次表: {batch_table_name}")
                if not self.check_table_exists(conn, batch_table_name):
                    logger.warning(f"批次表不存在，跳过插入: {batch_table_name}")
                else:
                    insert_batch_query = f"""
                        INSERT INTO {batch_table_name} (worker_id, batch_id, create_time)
                        VALUES (%s, %s, %s)
                    """
                    logger.info(f"    插入查询: {insert_batch_query}")
                    logger.info(f"    参数: worker_id={worker_id}, batch_id={batch_id}")

                    cursor.execute(insert_batch_query, (worker_id, batch_id, datetime.now()))
                    conn.commit()
                    logger.info(f"[步骤14] 批次记录插入成功")

            cursor.close()
            conn.close()

            logger.info("=" * 80)
            logger.info(f"批次生成完成!")
            if self.worker_id:
                logger.info(f"  Worker ID: {self.worker_id}")
            logger.info(f"  批次号: {batch_id}")
            logger.info(f"  处理记录数: {inserted_count}")
            logger.info("=" * 80)

            return True, batch_id, inserted_count

        except Exception as e:
            logger.error(f"执行批次生成失败: {str(e)}")
            logger.exception("详细错误信息:")
            if conn:
                conn.rollback()
                logger.info("事务已回滚")
                conn.close()
            return False, "", 0


def main():
    """主函数"""
    # 获取命令行参数
    if len(sys.argv) < 9:
        logger.error("参数不足!")
        logger.error("用法: python generate_batch.py <db_id> <db_ip> <db_port> <db_name> <db_user> <db_password> <skill_name> <config_dir> <worker_id>")
        logger.error("或使用完整参数: --db_id <id> --db_ip <ip> --db_port <port> --db_name <db> --db_user <user> --db_password <pwd> --skill_name <skill> --config_dir <dir> --worker_id <worker_id>")
        sys.exit(1)

    # 解析参数（支持两种格式）
    args = sys.argv[1:]

    # 简单参数格式
    if not args[0].startswith('--'):
        db_id, db_ip, db_port, db_name, db_user, db_password, skill_name, config_dir, worker_id = args[:9]
    else:
        # 完整参数格式
        params = {}
        for i in range(0, len(args), 2):
            params[args[i]] = args[i + 1]
        db_id = params.get('--db_id')
        db_ip = params.get('--db_ip')
        db_port = params.get('--db_port')
        db_name = params.get('--db_name')
        db_user = params.get('--db_user')
        db_password = params.get('--db_password')
        skill_name = params.get('--skill_name')
        config_dir = params.get('--config_dir')
        worker_id = params.get('--worker_id')

    logger.info("=" * 80)
    logger.info("批次生成脚本启动")
    logger.info("=" * 80)
    logger.info(f"参数:")
    logger.info(f"  数据库ID: {db_id}")
    logger.info(f"  数据库IP: {db_ip}")
    logger.info(f"  数据库端口: {db_port}")
    logger.info(f"  数据库名称: {db_name}")
    logger.info(f"  数据库用户: {db_user}")
    logger.info(f"  技能名称: {skill_name}")
    logger.info(f"  配置目录: {config_dir}")
    logger.info(f"  Worker ID: {worker_id}")

    # 设置文件日志（包含 worker_id）
    setup_file_logging(worker_id)

    # 构建配置文件路径
    db_map_path = os.path.join(config_dir, 'database_map.csv')
    table_map_path = os.path.join(config_dir, 'skill_table_map.csv')

    # 创建批次生成器
    generator = BatchGenerator(db_map_path, table_map_path, worker_id)

    # 加载配置
    if not generator.load_database_config():
        logger.error("加载数据库配置失败，退出")
        sys.exit(1)

    if not generator.load_table_mapping():
        logger.error("加载技能表映射配置失败，退出")
        sys.exit(1)

    # 覆盖数据库连接配置（使用命令行传入的参数）
    generator.db_connections[db_id] = {
        'ip': db_ip,
        'port': int(db_port),
        'db': db_name,
        'user': db_user,
        'password': db_password
    }
    logger.info(f"使用命令行参数覆盖数据库配置: {db_id}")

    # 执行批次生成
    success, batch_id, count = generator.execute_batch_generation(db_id, skill_name, worker_id)

    if success:
        logger.info(f"执行成功! Worker ID: {worker_id}, 批次号: {batch_id}, 处理记录数: {count}")
        # 输出JSON格式结果便于解析
        print(f"{{\"success\": true, \"worker_id\": \"{worker_id}\", \"batch_id\": \"{batch_id}\", \"count\": {count}}}")
        sys.exit(0)
    else:
        logger.error(f"执行失败! Worker ID: {worker_id}")
        print(f"{{\"success\": false, \"worker_id\": \"{worker_id}\", \"batch_id\": \"{batch_id}\", \"count\": {count}}}")
        sys.exit(1)


if __name__ == '__main__':
    main()
