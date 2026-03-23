#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量执行行处理脚本 - 实现阶段二到四
功能: 按行读取CSV/数据库数据，调用指定技能，记录结果
注意: 阶段一（输入验证）由 Claude Skill 在 skill.md 中处理，本脚本专注阶段2-4
"""

import csv
import json
import sys
import subprocess
import io
import os
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List




# ========== 配置日志目录（在脚本的外层目录下） ==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
LOG_DIR = os.path.join(PARENT_DIR, 'tmp')
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# log_file 将在获取 worker_id 后动态设置
log_file = None


# ========== 初始化日志（先只用控制台输出） ==========
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
    log_file = os.path.join(LOG_DIR, f'batch_executor_worker_{worker_id}.log')

    # 添加新的文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)


# ========== 雪花算法实现 ==========
class SnowflakeGenerator:
    """雪花算法ID生成器"""

    # 起始时间戳 (2024-01-01 00:00:00)
    TWITTER_EPOCH = 1704067200000

    def __init__(self, datacenter_id: int = 0, worker_id: int = 0):
        """
        初始化雪花算法生成器

        Args:
            datacenter_id: 数据中心ID (0-31)
            worker_id: 工作机器ID (0-31)
        """
        self.datacenter_id = datacenter_id & 0x1F  # 5位
        self.worker_id = worker_id & 0x1F  # 5位
        self.sequence = 0  # 12位序列号
        self.last_timestamp = -1  # 上次生成ID的时间戳

    def _current_millis(self) -> int:
        """获取当前毫秒时间戳"""
        return int(time.time() * 1000)

    def _wait_next_millis(self, last_timestamp: int) -> int:
        """等待到下一毫秒"""
        timestamp = self._current_millis()
        while timestamp <= last_timestamp:
            timestamp = self._current_millis()
        return timestamp

    def generate_id(self) -> int:
        """
        生成唯一的64位ID

        返回格式:
        - 1位符号位(永远为0)
        - 41位时间戳(相对于起始时间)
        - 5位数据中心ID
        - 5位工作机器ID
        - 12位序列号
        """
        timestamp = self._current_millis()

        # 时钟回拨处理
        if timestamp < self.last_timestamp:
            # 时钟回拨，等待时钟追上
            timestamp = self._wait_next_millis(self.last_timestamp)

        # 同一毫秒内，序列号自增
        if timestamp == self.last_timestamp:
            self.sequence = (self.sequence + 1) & 0xFFF  # 12位，最大4095
            if self.sequence == 0:
                # 序列号溢出，等待下一毫秒
                timestamp = self._wait_next_millis(self.last_timestamp)
        else:
            # 新的毫秒，序列号重置
            self.sequence = 0

        self.last_timestamp = timestamp

        # 组装ID
        snowflake_id = (
            ((timestamp - self.TWITTER_EPOCH) << 22)  # 41位时间戳
            | (self.datacenter_id << 17)  # 5位数据中心ID
            | (self.worker_id << 12)  # 5位工作机器ID
            | self.sequence  # 12位序列号
        )

        return snowflake_id

# 强制UTF-8编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 导入 run_claude 函数
sys.path.insert(0, str(Path(__file__).parent))
from run_claude import run_claude


class RowBatchExecutor:
    """行批量执行器 - 实现阶段二到四的流程"""

    def __init__(self, data_src_path: str, skill_name: str):
        """
        初始化执行器

        Args:
            data_src_path: 数据源路径（已验证，CSV文件或DB_开头）
            skill_name: 技能名称（已验证）
        """
        self.data_src_path = data_src_path
        self.skill_name = skill_name

        # 使用雪花算法生成唯一的 worker_id
        snowflake = SnowflakeGenerator(datacenter_id=1, worker_id=1)
        self.worker_id = snowflake.generate_id()

        # 生成主技能的 agent_name（格式：skill_name小写 + "_worker1"）
        self.agent_name = f"{skill_name.lower()}_worker1"

        # 设置文件日志（在获取 worker_id 后）
        setup_file_logging(str(self.worker_id))

        logger.info("=" * 80)
        logger.info("批量执行器初始化")
        logger.info(f"已生成 worker_id: {self.worker_id}")
        logger.info(f"主技能 Agent 名称: {self.agent_name}")
        logger.info("=" * 80)

        self.script_dir = Path(__file__).parent
        self.skill_dir = self.script_dir.parent
        self.config_dir = self.skill_dir / "config"

        # 结果输出目录
        self.output_dir = Path("row_batch_output")
        self.output_dir.mkdir(exist_ok=True)

        # 结果映射文件（执行时初始化）
        self.record_map_file: Optional[Path] = None

        # 加载配置表
        self.skill_table_map = self._load_skill_table_map()
        self.database_map = self._load_database_map()
        self.skill_config = None  # 当前技能的配置
        self.continue_on_failure = True  # 默认为True，执行时根据配置更新
        self.batch_id = None  # 当前 worker 对应的批次ID（执行时初始化）

        # 获取根目录（.claude 或 .openclaw 的父目录）
        self.root_dir = self._find_root_dir()

        # 获取环境目录名（.claude 或 .openclaw）
        self.env_dir = self._get_env_dir()

    def _find_root_dir(self) -> Path:
        """
        查找根目录（.claude 或 .openclaw 的父目录）

        Returns:
            根目录路径
        """
        current_dir = Path(__file__).resolve()

        # 向上查找路径以 .claude 或 .openclaw 结尾的目录
        for parent in [current_dir, *current_dir.parents]:
            # 优先查找以 .claude 结尾的目录
            if parent.name == '.claude':
                return parent.parent
            # 如果找不到 .claude，尝试查找以 .openclaw 结尾的目录
            if parent.name == '.openclaw':
                return parent.parent

        # 如果找不到，使用当前目录的父目录的父目录（假设在 scripts 目录中）
        return current_dir.parent.parent

    def _get_env_dir(self) -> str:
        """
        获取环境目录名（.claude 或 .openclaw）

        Returns:
            环境目录名
        """
        current_dir = Path(__file__).resolve()

        # 向上查找路径以 .claude 或 .openclaw 结尾的目录
        for parent in [current_dir, *current_dir.parents]:
            # 优先查找以 .claude 结尾的目录
            if parent.name == '.claude':
                return '.claude'
            # 如果找不到 .claude，尝试查找以 .openclaw 结尾的目录
            if parent.name == '.openclaw':
                return '.openclaw'

        # 如果找不到，默认返回 .claude
        return '.claude'

    def _get_secondary_root_dirs(self) -> List[Path]:
        """
        获取第二个根目录列表
        固定在 /app 目录下，文件夹名称为主技能名称转小写+_worker+序号
        遍历 /app 目录下的所有文件夹，匹配符合模式的目录

        Returns:
            第二个根目录路径列表
        """
        secondary_dirs = []
        app_dir = Path('/app')

        # 如果 /app 目录不存在，返回空列表
        if not app_dir.exists():
            logger.info(f"[信息] /app 目录不存在，第二个根目录列表为空")
            return secondary_dirs

        # 主技能名称转小写
        skill_name_lower = self.skill_name.lower()
        # 匹配模式：{skill_name_lower}_worker
        worker_prefix = f"workspace-{skill_name_lower}_worker"

        # 遍历 /app 目录下的所有文件夹
        try:
            for item in app_dir.iterdir():
                # 只处理目录
                if item.is_dir():
                    dir_name = item.name
                    # 检查目录名称是否以 {skill_name_lower}_worker 开头
                    if dir_name.startswith(worker_prefix):
                        secondary_dirs.append(item)
                        logger.info(f"[信息] 找到第二个根目录: {item}")
        except PermissionError as e:
            logger.warning(f"[警告] 无法访问 /app 目录: {e}")

        # 按目录名称排序（确保 worker1, worker2, ... 的顺序）
        secondary_dirs.sort(key=lambda x: x.name)

        logger.info(f"[信息] 第二个根目录列表共 {len(secondary_dirs)} 个")
        return secondary_dirs

    def _load_skill_table_map(self) -> Dict[str, Dict[str, str]]:
        """加载技能表映射"""
        skill_map = {}
        map_file = self.config_dir / "skill_table_map.csv"

        if not map_file.exists():
            raise FileNotFoundError(f"技能表映射文件不存在: {map_file}")

        try:
            with open(map_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row and 'skill_name' in row:
                        skill_name = row['skill_name'].strip()
                        skill_map[skill_name] = {
                            'continue_on_failure': row.get('continue_on_failure', '1').strip() == '1',
                            'output_skill_name': row.get('output_skill_name', '').strip(),
                            'output_skill_py': row.get('output_skill_py', '').strip(),
                            'output_skill_py_params': row.get('output_skill_py_params', '').strip(),
                            'pre_skill_name': row.get('pre_skill_name', '').strip(),
                            'input_table_name': row.get('input_table_name', '').strip(),
                            'input_table_flds': row.get('input_table_flds', '').strip(),
                            'select_condition': row.get('select_condition', '').strip(),
                            'update_condition': row.get('update_condition', '').strip(),
                            'output_table_name': row.get('output_table_name', '').strip(),
                            'output_table_flds': row.get('output_table_flds', '').strip(),
                            'batch_table_name': row.get('batch_table_name', '').strip(),
                            'batch_id_fld': row.get('batch_id_fld', '').strip(),
                            'check_condition': row.get('check_condition', '').strip(),
                        }
        except Exception as e:
            raise ValueError(f"读取技能表映射失败: {e}")

        return skill_map

    def _load_database_map(self) -> Dict[str, Dict[str, str]]:
        """加载数据库连接信息映射"""
        db_map = {}
        map_file = self.config_dir / "database_map.csv"

        if not map_file.exists():
            raise FileNotFoundError(f"数据库映射文件不存在: {map_file}")

        try:
            with open(map_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row and 'id' in row:
                        db_id = row['id'].strip()
                        db_map[db_id] = {
                            'ip': row.get('ip', '').strip(),
                            'port': row.get('port', '').strip(),
                            'db': row.get('db', '').strip(),
                            'user': row.get('user', '').strip(),
                            'password': row.get('password', '').strip(),
                        }
        except Exception as e:
            raise ValueError(f"读取数据库映射失败: {e}")

        return db_map

    def _get_batch_id_by_worker(self, batch_table_name: str, batch_id_fld: str) -> Optional[str]:
        """
        根据 worker_id 从批次表中查询对应的 batch_id

        Args:
            batch_table_name: 批次表名
            batch_id_fld: batch_id 字段名称

        Returns:
            batch_id，如果查询失败则返回 None
        """
        try:
            db_id = self.data_src_path
            if db_id not in self.database_map:
                logger.info(f"[警告] 数据库ID不存在: {db_id}")
                return None

            db_config = self.database_map[db_id]

            # 导入 psycopg2
            import psycopg2

            # 连接数据库
            conn = psycopg2.connect(
                host=db_config['ip'],
                port=int(db_config['port']),
                database=db_config['db'],
                user=db_config['user'],
                password=db_config['password']
            )

            cursor = conn.cursor()

            # 解析表名（包含 schema）
            schema_table = batch_table_name.split('.')
            if len(schema_table) == 2:
                schema, table = schema_table
            else:
                schema, table = 'public', schema_table[0]

            # 构建查询：根据 worker_id 获取 batch_id
            query_str = f"""
                SELECT {batch_id_fld}
                FROM {schema}.{table}
                WHERE worker_id = %s
                LIMIT 1
            """

            logger.info(f"[调试] 根据 worker_id 查询 batch_id 的 SQL: {query_str}")
            logger.info(f"[调试] worker_id: {self.worker_id}")

            cursor.execute(query_str, (str(self.worker_id),))
            result = cursor.fetchone()

            cursor.close()
            conn.close()

            if result and result[0]:
                batch_id = str(result[0])
                logger.info(f"[信息] 根据 worker_id 查询到 batch_id: {batch_id}")
                return batch_id
            else:
                logger.info(f"[警告] 未找到 worker_id ({self.worker_id}) 对应的 batch_id")
                return None

        except Exception as e:
            logger.info(f"[警告] 查询 batch_id 失败: {e}")
            return None

    # ========== 阶段二前置：执行前置技能 ==========
    def execute_pre_skills(self) -> None:
        """
        阶段二前置：在取数之前执行前置技能

        前置技能使用与row-batch相同的传参格式（包含data_src_path和skill_name）
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"[阶段二前置] 开始 - 执行前置技能")
        logger.info(f"{'='*60}")

        # 获取前置技能名称
        pre_skill_name = self.skill_config.get('pre_skill_name', '')

        if not pre_skill_name:
            logger.info(f"[阶段二前置] 结束 - 无前置技能需要执行")
            logger.info(f"{'='*60}")
            return

        # 处理前置技能（可能多个，用逗号分隔）
        pre_skills = [s.strip() for s in pre_skill_name.split(',') if s.strip()]

        # 前置技能使用与row-batch相同的传参格式
        pre_skill_input = {"data_src_path": self.data_src_path, "skill_name": self.skill_name}

        for pre_skill in pre_skills:
            # 将 worker_id 添加到输入数据中
            skill_input_with_worker = {**pre_skill_input, "worker_id": self.worker_id}
            logger.info(f"[阶段二前置] 执行前置技能: {pre_skill}")
            logger.info(f"[阶段二前置] 输入数据: {skill_input_with_worker}")

            try:
                # 使用 run_claude 函数调用前置技能，传递 worker_id、output_dir 和 agent_name（前置技能使用主技能的agent_name）
                exit_code = run_claude(pre_skill, skill_input_with_worker, str(self.worker_id), str(self.output_dir), self.agent_name)

                if exit_code == 0:
                    logger.info(f"[阶段二前置] 前置技能 {pre_skill} 执行成功")
                else:
                    logger.info(f"[阶段二前置] 前置技能 {pre_skill} 执行失败，返回码: {exit_code}")
                    # 继续执行其他前置技能，不中断流程
            except Exception as e:
                logger.info(f"[阶段二前置] 前置技能 {pre_skill} 执行异常: {e}")
                # 继续执行其他前置技能，不中断流程

        logger.info(f"[阶段二前置] 结束 - 前置技能执行完成")
        logger.info(f"{'='*60}")

    # ========== 阶段二：按行读取输入的指定字段 ==========
    def read_next_row(self) -> Dict[str, Any]:
        """
        阶段二：按行读取输入的指定字段
        通过调用 read_csv_row.py 或 read_db_row.py 脚本获取数据

        Returns:
            读取到的数据（JSON格式），如果没有更多行则返回空字典
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"[阶段二] 开始 - 按行读取输入的指定字段")
        logger.info(f"{'='*60}")

        input_table_flds_str = self.skill_config['input_table_flds']
        logger.info(f"[阶段二] 配置字段: {input_table_flds_str}")

        # 判断数据源类型
        if self.data_src_path.startswith('DB_'):
            # 数据库源处理
            db_id = self.data_src_path
            if db_id not in self.database_map:
                raise ValueError(f"数据库ID不存在: {db_id}")

            logger.info(f"[阶段二] 从数据库读取下一行...")

            try:
                db_config = self.database_map[db_id]
                table_name = self.skill_config['input_table_name']
                select_condition = self.skill_config['select_condition']
                update_condition = self.skill_config['update_condition']

                # 获取 batch_table_name 和 batch_id_fld 配置
                batch_table_name = self.skill_config.get('batch_table_name', '').strip()
                batch_id_fld = self.skill_config.get('batch_id_fld', '').strip()

                # 如果配置了批次表和批次ID字段，使用已获取的 batch_id 添加到筛选条件
                if batch_table_name and batch_id_fld and self.batch_id:
                    # 添加 batch_id 过滤条件到 select_condition（使用 batch_id_fld 作为字段名）
                    if select_condition:
                        select_condition = f"({select_condition}) AND {batch_id_fld} = '{self.batch_id}'"
                    else:
                        select_condition = f"{batch_id_fld} = '{self.batch_id}'"
                    logger.info(f"[阶段二] 已添加 {batch_id_fld} 过滤条件，最终筛选条件: {select_condition}")
                elif batch_table_name and batch_id_fld and not self.batch_id:
                    logger.info(f"[警告] 未获取到 batch_id，将使用原始筛选条件")

                # 调用 read_db_row.py 脚本
                result = subprocess.run(
                    [
                        sys.executable,
                        str(self.script_dir / "read_db_row.py"),
                        db_config['ip'],
                        db_config['port'],
                        db_config['db'],
                        db_config['user'],
                        db_config['password'],
                        table_name,
                        input_table_flds_str,
                        select_condition,
                        update_condition
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    encoding='utf-8',
                    errors='replace',
                    check=False
                )

                if result.returncode != 0:
                    if result.stderr:
                        raise RuntimeError(f"read_db_row.py 执行失败: {result.stderr}")
                    else:
                        raise RuntimeError(f"read_db_row.py 执行失败")

                # 解析输出的 JSON 数据
                output = result.stdout.strip()
                if not output:
                    return {}

                row_data = json.loads(output)

                if not row_data:
                    # 没有更多未读行
                    return {}

                # id 转换为 poi_id
                if 'id' in row_data:
                    row_data['poi_id'] = row_data.pop('id')

                logger.info(f"[阶段二] 结束 - 成功读取行数据: {row_data.get('task_id', row_data.get('poi_id', 'N/A'))}")
                logger.info(f"{'='*60}")
                return row_data

            except json.JSONDecodeError as e:
                logger.info(f"[阶段二] 结束 - 解析失败: {e}")
                logger.info(f"{'='*60}")
                raise ValueError(f"解析 read_db_row.py 的输出失败: {e}")
            except Exception as e:
                raise RuntimeError(f"调用 read_db_row.py 失败: {e}")

        elif self.data_src_path.endswith('.csv'):
            # CSV 源处理 - 通过 subprocess 调用 read_csv_row.py
            logger.info(f"[阶段二] 从CSV文件读取下一行...")

            try:
                # 调用 read_csv_row.py 脚本
                result = subprocess.run(
                    [
                        sys.executable,
                        str(self.script_dir / "read_csv_row.py"),
                        self.data_src_path,
                        input_table_flds_str
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    encoding='utf-8',
                    errors='replace',
                    check=False
                )

                if result.returncode != 0:
                    if result.stderr:
                        raise RuntimeError(f"read_csv_row.py 执行失败: {result.stderr}")
                    else:
                        raise RuntimeError(f"read_csv_row.py 执行失败")

                # 解析输出的 JSON 数据
                output = result.stdout.strip()
                if not output:
                    return {}

                row_data = json.loads(output)

                if not row_data:
                    # 没有更多未读行
                    return {}

                # id 转换为 poi_id
                if 'id' in row_data:
                    row_data['poi_id'] = row_data.pop('id')

                logger.info(f"[阶段二] 结束 - 成功读取行数据: {row_data.get('task_id', row_data.get('poi_id', 'N/A'))}")
                logger.info(f"{'='*60}")
                return row_data

            except json.JSONDecodeError as e:
                logger.info(f"[阶段二] 结束 - 解析失败: {e}")
                logger.info(f"{'='*60}")
                raise ValueError(f"解析 read_csv_row.py 的输出失败: {e}")
            except Exception as e:
                raise RuntimeError(f"调用 read_csv_row.py 失败: {e}")

        else:
            raise ValueError(f"不支持的数据源类型: {self.data_src_path}")

    # ========== 阶段三：指定技能调用 ==========
    def _parse_output_params(self, params_str: str, row_data: Dict[str, Any], root_dir: Path) -> List[str]:
        """
        解析回库脚本的参数

        Args:
            params_str: 参数字符串，例如 "task_id,'./output/results'"
            row_data: 行数据
            root_dir: 根目录路径，用于拼接相对路径

        Returns:
            解析后的参数列表
        """
        if not params_str or not params_str.strip():
            return []

        params = []
        # 使用正则表达式分割参数（考虑引号）
        import re
        # 匹配不带引号的词或带引号的字符串
        pattern = r'(\w+)|\'([^\']*)\'|"([^"]*)"'
        matches = re.findall(pattern, params_str)

        for match in matches:
            word, single_quoted, double_quoted = match
            if word:
                # 不带引号，从 row_data 中获取值
                value = row_data.get(word, '')
                params.append(str(value))
            elif single_quoted is not None:
                # 单引号包裹
                if single_quoted.startswith('./') or single_quoted.startswith('../') or single_quoted.startswith('/'):
                    # 是路径，与根目录拼接
                    full_path = root_dir / single_quoted
                    params.append(str(full_path))
                else:
                    # 常量
                    params.append(single_quoted)
            elif double_quoted is not None:
                # 双引号包裹，处理方式同单引号
                if double_quoted.startswith('./') or double_quoted.startswith('../') or double_quoted.startswith('/'):
                    full_path = root_dir / double_quoted
                    params.append(str(full_path))
                else:
                    params.append(double_quoted)

        return params

    def _execute_output_script(self, output_skill_py: str, output_skill_py_params: str, row_data: Dict[str, Any]) -> bool:
        """
        执行回库脚本，支持多个根目录的回退重试

        Args:
            output_skill_py: 回库脚本路径（相对于根目录，支持 {env} 占位符）
            output_skill_py_params: 回库脚本参数
            row_data: 行数据

        Returns:
            是否执行成功
        """
        # 替换 {env} 占位符为实际的环境目录名
        output_skill_py_resolved = output_skill_py.replace('{env}', self.env_dir)

        # 只在第一个根目录中查找脚本
        script_path = self.root_dir / output_skill_py_resolved

        if not script_path.exists():
            logger.info(f"[阶段三-回库] 回库脚本不存在: {script_path}")
            logger.info(f"[阶段三-回库] 原始路径: {output_skill_py}")
            logger.info(f"[阶段三-回库] 环境目录: {self.env_dir}")
            logger.info(f"[阶段三-回库] 解析后路径: {output_skill_py_resolved}")
            logger.info(f"[阶段三-回库] 第一个根目录: {self.root_dir}")
            return False

        logger.info(f"[阶段三-回库] 找到回库脚本: {script_path}")

        # 动态获取第二个根目录列表（在执行完主技能后，可能每次结果不同）
        secondary_root_dirs = self._get_secondary_root_dirs()

        # 构建根目录列表：第一个根目录 + 第二个根目录列表（用于参数解析）
        root_dirs = [self.root_dir] + secondary_root_dirs

        logger.info(f"[阶段三-回库] 参数解析根目录列表共 {len(root_dirs)} 个")

        # 遍历所有根目录，使用不同的参数尝试执行回库脚本
        for idx, root_dir in enumerate(root_dirs):
            try:
                logger.info(f"[阶段三-回库] 尝试第 {idx + 1}/{len(root_dirs)} 个根目录解析参数: {root_dir}")

                # 解析参数（传入当前使用的根目录）
                params = self._parse_output_params(output_skill_py_params, row_data, root_dir)

                logger.info(f"[阶段三-回库] 执行回库脚本")
                logger.info(f"[阶段三-回库] 原始路径: {output_skill_py}")
                logger.info(f"[阶段三-回库] 环境目录: {self.env_dir}")
                logger.info(f"[阶段三-回库] 解析后路径: {output_skill_py_resolved}")
                logger.info(f"[阶段三-回库] 脚本路径: {script_path}")
                logger.info(f"[阶段三-回库] 参数解析根目录: {root_dir}")
                logger.info(f"[阶段三-回库] 参数: {params}")

                # 获取脚本所在目录
                script_dir = script_path.parent

                # 构建命令：进入到脚本所在目录，然后执行
                cmd = [sys.executable, str(script_path.name)] + params

                logger.info(f"[阶段三-回库] 执行命令: cd {script_dir} && {' '.join(cmd)}")

                # 执行命令
                result = subprocess.run(
                    cmd,
                    cwd=str(script_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    encoding='utf-8',
                    errors='replace',
                    check=False
                )

                # 打印输出
                if result.stdout:
                    logger.info(f"[阶段三-回库] 标准输出:\n{result.stdout}")
                if result.stderr:
                    logger.info(f"[阶段三-回库] 标准错误:\n{result.stderr}")

                # 判断回库脚本是否执行成功
                execution_success = True

                # 尝试从 stdout 中解析 success 状态
                if result.stdout and result.stdout.strip():
                    # 逐行扫描，查找包含带双引号的 "success" 的行
                    success_found = False
                    for line in result.stdout.splitlines():
                        line_lower = line.lower()
                        # 检查行中是否包含带双引号的 "success"
                        if '"success"' in line_lower or "'success'" in line_lower:
                            success_found = True
                            # 检查是否包含 false
                            if 'false' in line_lower:
                                execution_success = False
                                logger.info(f"[阶段三-回库] 回库脚本输出包含 success=false（参数解析根目录: {root_dir}）")
                                logger.info(f"[阶段三-回库] 相关行: {line.strip()}")
                                break  # 找到失败标记，停止扫描
                            # 检查是否包含 true
                            elif 'true' in line_lower:
                                execution_success = True
                                logger.info(f"[阶段三-回库] 回库脚本输出包含 success=true（参数解析根目录: {root_dir}）")
                                logger.info(f"[阶段三-回库] 相关行: {line.strip()}")
                                break  # 找到成功标记，停止扫描

                    if not success_found:
                        # 没有找到包含 "success" 的行，保持默认成功
                        logger.info(f"[阶段三-回库] 未在输出中找到 \"success\" 标记，默认成功（参数解析根目录: {root_dir}）")
                else:
                    # stdout 为空，默认成功
                    logger.info(f"[阶段三-回库] 输出为空，默认成功（参数解析根目录: {root_dir}）")

                # 同时考虑 returncode
                if result.returncode != 0:
                    execution_success = False
                    logger.info(f"[阶段三-回库] 回库脚本返回码非零: {result.returncode}（参数解析根目录: {root_dir}）")

                if execution_success:
                    logger.info(f"[阶段三-回库] 回库脚本执行成功（参数解析根目录: {root_dir}）")
                    return True
                else:
                    logger.info(f"[阶段三-回库] 回库脚本执行失败（参数解析根目录: {root_dir}）")
                    # 继续尝试下一个根目录
                    continue

            except Exception as e:
                logger.info(f"[阶段三-回库] 执行异常（参数解析根目录: {root_dir}）: {str(e)}")
                import traceback
                traceback.print_exc()
                # 继续尝试下一个根目录
                continue

        # 所有根目录都尝试失败
        logger.info(f"[阶段三-回库] 所有参数解析根目录均执行失败")
        return False

    def _check_result_condition(self, row_data: Dict[str, Any]) -> bool:
        """
        检查主键 + check_condition 是否为空

        Args:
            row_data: 行数据

        Returns:
            True 表示检查通过（非空），False 表示检查失败（为空，需要重试）
        """
        try:
            check_condition = self.skill_config.get('check_condition', '').strip()

            # 如果没有配置 check_condition，则默认通过
            if not check_condition:
                logger.info(f"[阶段三-回库检查] 未配置 check_condition，跳过检查")
                return True

            # 只对数据库源进行检查
            if not self.data_src_path.startswith('DB_'):
                logger.info(f"[阶段三-回库检查] 非数据库源，跳过检查")
                return True

            db_id = self.data_src_path
            if db_id not in self.database_map:
                logger.info(f"[阶段三-回库检查] 数据库ID不存在: {db_id}，跳过检查")
                return True

            db_config = self.database_map[db_id]
            table_name = self.skill_config['input_table_name']

            # 导入 psycopg2
            import psycopg2

            # 连接数据库
            conn = psycopg2.connect(
                host=db_config['ip'],
                port=int(db_config['port']),
                database=db_config['db'],
                user=db_config['user'],
                password=db_config['password']
            )

            cursor = conn.cursor()

            # 解析表名（包含 schema）
            schema_table = table_name.split('.')
            if len(schema_table) == 2:
                schema, table = schema_table
            else:
                schema, table = 'public', schema_table[0]

            # 自动获取表的主键字段
            logger.info(f"[阶段三-回库检查] 查询表 {schema}.{table} 的主键字段...")

            # 查询 PostgreSQL 系统表获取主键字段
            primary_key_query = f"""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = '{schema}.{table}'::regclass AND i.indisprimary
                ORDER BY a.attnum
            """

            cursor.execute(primary_key_query)
            primary_key_result = cursor.fetchone()

            if not primary_key_result or not primary_key_result[0]:
                logger.info(f"[阶段三-回库检查] 无法获取表的主键字段，跳过检查")
                cursor.close()
                conn.close()
                return True

            primary_key_field = primary_key_result[0]
            logger.info(f"[阶段三-回库检查] 获取到主键字段: {primary_key_field}")

            primary_key_value = row_data.get(primary_key_field)

            if not primary_key_value:
                logger.info(f"[阶段三-回库检查] 无法获取主键值（字段: {primary_key_field}），跳过检查")
                cursor.close()
                conn.close()
                return True

            # 构建查询条件：主键 + check_condition
            query_condition = f"{primary_key_field} = '{primary_key_value}'"
            if check_condition:
                query_condition = f"{query_condition} AND {check_condition}"

            # 构建查询 SQL
            query_str = f"""
                SELECT COUNT(*)
                FROM {schema}.{table}
                WHERE {query_condition}
            """

            logger.info(f"[阶段三-回库检查] 检查 SQL: {query_str}")

            cursor.execute(query_str)
            result = cursor.fetchone()

            cursor.close()
            conn.close()

            count = result[0] if result else 0

            if count > 0:
                logger.info(f"[阶段三-回库检查] 检查通过 - 找到 {count} 条符合条件的记录")
                return True
            else:
                logger.info(f"[阶段三-回库检查] 检查失败 - 未找到符合条件的记录（主键: {primary_key_field}={primary_key_value}, 条件: {check_condition}）")
                return False

        except Exception as e:
            logger.info(f"[阶段三-回库检查] 检查异常: {e}")
            import traceback
            traceback.print_exc()
            # 发生异常时默认通过，避免无限重试
            return True

    def call_skill(self, row_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段三：指定技能调用（支持重试机制）

        Args:
            row_data: 行数据

        Returns:
            技能执行结果
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"[阶段三] 开始 - 调用技能: {self.skill_name}")
        logger.info(f"{'='*60}")

        try:
            # 获取回库脚本配置
            output_skill_py = self.skill_config.get('output_skill_py', '').strip()
            output_skill_py_params = self.skill_config.get('output_skill_py_params', '').strip()

            # 最大重试次数
            max_retries = 5
            all_success = False

            # 重试循环：包含主技能执行、回库脚本执行、结果检查
            for retry_count in range(1, max_retries + 1):
                logger.info(f"\n{'='*60}")
                logger.info(f"[阶段三] 第 {retry_count} 次尝试（最大重试次数: {max_retries}）")
                logger.info(f"{'='*60}")

                # 将 worker_id 添加到输入数据中
                skill_input_with_worker = {**row_data, "worker_id": self.worker_id}
                logger.info(f"[阶段三] 输入数据: {skill_input_with_worker}")

                # 执行主技能
                logger.info(f"[阶段三] 开始执行主技能")
                exit_code = run_claude(self.skill_name, skill_input_with_worker, str(self.worker_id), str(self.output_dir), self.agent_name)

                if exit_code != 0:
                    logger.info(f"[阶段三] 主技能执行失败，返回码: {exit_code}")
                    if retry_count < max_retries:
                        logger.info(f"[阶段三] 准备重试，剩余重试次数: {max_retries - retry_count}")
                        continue
                    else:
                        logger.info(f"[阶段三] 已达到最大重试次数 ({max_retries})，结束重试")
                        if self.continue_on_failure:
                            logger.info(f"[阶段三] 警告 - 主技能执行失败，根据配置继续处理下一行")
                            logger.info(f"{'='*60}")
                            return {
                                "status": "skipped",
                                "error": f"主技能执行失败，已重试 {retry_count} 次",
                                "skill": self.skill_name,
                                "input": row_data
                            }
                        else:
                            logger.info(f"[阶段三] 错误 - 主技能执行失败，结束整体执行")
                            logger.info(f"{'='*60}")
                            return {
                                "status": "error",
                                "error": f"主技能执行失败，已重试 {retry_count} 次",
                                "skill": self.skill_name,
                                "input": row_data
                            }

                logger.info(f"[阶段三] 主技能执行成功")

                # 如果配置了回库脚本，执行回库脚本并进行结果检查
                if output_skill_py:
                    logger.info(f"[阶段三] 开始执行回库脚本")
                    output_success = self._execute_output_script(output_skill_py, output_skill_py_params, skill_input_with_worker)

                    if not output_success:
                        logger.info(f"[阶段三] 回库脚本执行失败")
                        if retry_count < max_retries:
                            logger.info(f"[阶段三] 准备重试，剩余重试次数: {max_retries - retry_count}")
                            continue
                        else:
                            logger.info(f"[阶段三] 已达到最大重试次数 ({max_retries})，结束重试")
                            if self.continue_on_failure:
                                logger.info(f"[阶段三] 警告 - 回库脚本执行失败，根据配置继续处理下一行")
                                logger.info(f"{'='*60}")
                                return {
                                    "status": "skipped",
                                    "error": f"回库脚本执行失败，已重试 {retry_count} 次",
                                    "skill": self.skill_name,
                                    "input": row_data
                                }
                            else:
                                logger.info(f"[阶段三] 错误 - 回库脚本执行失败，结束整体执行")
                                logger.info(f"{'='*60}")
                                return {
                                    "status": "error",
                                    "error": f"回库脚本执行失败，已重试 {retry_count} 次",
                                    "skill": self.skill_name,
                                    "input": row_data
                                }

                    logger.info(f"[阶段三] 回库脚本执行成功")

                    # 回库成功后，检查主键+check_condition是否为空
                    logger.info(f"\n{'='*60}")
                    logger.info(f"[阶段三] 开始检查回库结果")
                    logger.info(f"{'='*60}")
                    check_passed = self._check_result_condition(skill_input_with_worker)

                    if check_passed:
                        logger.info(f"[阶段三] 回库结果检查通过（第 {retry_count} 次尝试）")
                        all_success = True
                        break
                    else:
                        logger.info(f"[阶段三] 回库结果检查失败 - 第 {retry_count} 次尝试未通过")
                        if retry_count < max_retries:
                            logger.info(f"[阶段三] 准备重试，剩余重试次数: {max_retries - retry_count}")
                        else:
                            logger.info(f"[阶段三] 已达到最大重试次数 ({max_retries})，结束重试")
                else:
                    # 没有配置回库脚本，主技能成功即可
                    logger.info(f"[阶段三] 未配置回库脚本，跳过回库步骤")
                    all_success = True
                    break

            # 最终状态判断
            if not all_success:
                logger.info(f"\n{'='*60}")
                logger.info(f"[阶段三] 警告 - 经过 {max_retries} 次尝试后，仍未成功")
                if self.continue_on_failure:
                    logger.info(f"[阶段三] 根据配置跳过当前行，继续处理下一行")
                    logger.info(f"{'='*60}")
                    return {
                        "status": "skipped",
                        "error": f"回库结果检查失败，已重试 {max_retries} 次",
                        "skill": self.skill_name,
                        "input": row_data
                    }
                else:
                    logger.info(f"[阶段三] 结束整体执行，所有阶段停止")
                    logger.info(f"{'='*60}")
                    return {
                        "status": "error",
                        "error": f"阶段三执行失败，已重试 {max_retries} 次",
                        "skill": self.skill_name,
                        "input": row_data
                    }

            logger.info(f"\n{'='*60}")
            logger.info(f"[阶段三] 结束 - 技能执行成功")
            logger.info(f"{'='*60}")
            return {
                "status": "success",
                "skill": self.skill_name,
                "input": row_data
            }

        except Exception as e:
            logger.info(f"[阶段三] 结束 - 执行异常: {str(e)}")
            logger.info(f"{'='*60}")
            return {
                "status": "error",
                "error": str(e),
                "skill": self.skill_name,
                "input": row_data
            }

    # ========== 阶段四：记录每一行的输出结果 ==========
    def _save_output(self, row_number: int, result: Dict[str, Any]) -> str:
        """保存输出结果"""
        logger.info(f"\n{'='*60}")
        logger.info(f"[阶段四] 开始 - 保存输出结果")
        logger.info(f"{'='*60}")

        output_file = self.output_dir / f"result_worker_{self.worker_id}_row_{row_number}.json"

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"[阶段四] 结束 - 结果已保存到: {output_file}")
        logger.info(f"{'='*60}")
        return str(output_file)

    def _append_record_map(self, row_number: int, row_data: Dict[str, Any]) -> None:
        """
        阶段四：记录行号与输入数据的映射关系
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"[阶段四] 开始 - 记录行映射关系")
        logger.info(f"{'='*60}")

        # 如果是第一次写入，需要写入头
        is_first = not self.record_map_file.exists()

        with open(self.record_map_file, 'a', encoding='utf-8', newline='') as f:
            if is_first:
                f.write("row_number,data\n")

            # 将行数据转换为 JSON 字符串
            data_json = json.dumps(row_data, ensure_ascii=False)
            f.write(f'{row_number},"{data_json}"\n')

        logger.info(f"[阶段四] 结束 - 映射关系已记录")
        logger.info(f"{'='*60}")

    # ========== 主执行流程 ==========
    def execute(self) -> None:
        """
        执行阶段二到四的批量处理流程
        （阶段一由 Claude 在 skill.md 中处理）
        """
        try:
            # 初始化 record_map_file（包含 worker_id）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.record_map_file = self.output_dir / f"record_map_worker_{self.worker_id}_{timestamp}.csv"

            logger.info("\n" + "="*80)
            logger.info(f"开始批量处理: {self.skill_name}")
            logger.info(f"数据源: {self.data_src_path}")
            logger.info(f"Worker ID: {self.worker_id}")
            logger.info("="*80)

            # 初始化技能配置（需要在执行前置技能之前完成）
            if self.skill_name not in self.skill_table_map:
                raise ValueError(f"技能未在映射表中: {self.skill_name}")
            self.skill_config = self.skill_table_map[self.skill_name]
            # 从配置中更新 continue_on_failure 值
            self.continue_on_failure = self.skill_config.get('continue_on_failure', True)
            logger.info(f"重试失败处理策略: {'继续下一行' if self.continue_on_failure else '直接退出程序'}")

            # 【阶段二前置】执行前置技能（在取数前执行）
            self.execute_pre_skills()

            # 【初始化 batch_id】根据 worker_id 获取批次号（只调用一次，在前置技能执行完之后）
            batch_table_name = self.skill_config.get('batch_table_name', '').strip()
            batch_id_fld = self.skill_config.get('batch_id_fld', '').strip()
            if batch_table_name and batch_id_fld and self.data_src_path.startswith('DB_'):
                self.batch_id = self._get_batch_id_by_worker(batch_table_name, batch_id_fld)
                if self.batch_id:
                    logger.info(f"[初始化] 已获取 batch_id: {self.batch_id}")
                else:
                    logger.info(f"[警告] 无法根据 worker_id 获取 batch_id")

            # 【阶段二-四】循环处理
            row_number = 0
            total_rows = 0
            success_rows = 0
            error_rows = 0
            skipped_rows = 0

            while True:
                # 【阶段二】按行读取数据
                row_data = self.read_next_row()

                if not row_data:
                    logger.info(f"\n{'='*60}")
                    logger.info(f"[阶段二] 结束 - 没有更多数据")
                    logger.info(f"{'='*60}")
                    break

                row_number += 1
                total_rows += 1

                logger.info(f"\n>>> [第 {row_number} 行] 开始处理")

                # 【阶段三】调用技能
                result = self.call_skill(row_data)

                # 【阶段四】保存输出结果
                output_file = self._save_output(row_number, result)

                # 检查执行结果
                if result['status'] == 'error':
                    error_rows += 1
                    # 【阶段四】记录映射
                    self._append_record_map(row_number, row_data)
                    logger.info(f">>> [第 {row_number} 行] 处理失败 - 状态: error")
                    logger.info(f"\n{'='*80}")
                    logger.info(f"[错误] 第 {row_number} 行执行失败，结束所有阶段的执行")
                    logger.info(f"[错误] 错误信息: {result.get('error', 'Unknown error')}")
                    logger.info(f"{'='*80}")
                    sys.exit(1)
                elif result['status'] == 'skipped':
                    skipped_rows += 1
                    # 【阶段四】记录映射
                    self._append_record_map(row_number, row_data)
                    logger.info(f">>> [第 {row_number} 行] 跳过处理 - 状态: skipped（根据配置继续下一行）")
                    logger.info(f"[跳过原因] {result.get('error', 'Unknown reason')}")
                    continue

                success_rows += 1

                # 【阶段四】记录映射
                self._append_record_map(row_number, row_data)

                logger.info(f">>> [第 {row_number} 行] 处理完成 - 状态: {result['status']}")

            # 输出统计信息
            logger.info("\n" + "="*80)
            logger.info("批量处理完成")
            logger.info("="*80)
            logger.info(f"总处理行数: {total_rows}")
            logger.info(f"成功: {success_rows}")
            logger.info(f"跳过: {skipped_rows}")
            logger.info(f"失败: {error_rows}")
            logger.info(f"记录映射文件: {self.record_map_file}")

        except Exception as e:
            logger.info(f"\n[ERROR] 执行错误: {str(e)}")
            sys.exit(1)


def main():
    """主函数 - 接收来自 Claude 的已验证参数"""
    # 从命令行参数读取输入数据（阶段一已由 Claude 验证）
    if len(sys.argv) < 3:
        print("用法: python batch_executor.py <data_src_path> <skill_name>", file=sys.stderr)
        print("示例: python batch_executor.py ./test.csv skills-bigpoi-verification", file=sys.stderr)
        sys.exit(1)

    data_src_path = sys.argv[1]
    skill_name = sys.argv[2]

    try:
        executor = RowBatchExecutor(data_src_path, skill_name)
        executor.execute()
    except Exception as e:
        print(f"错误: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
