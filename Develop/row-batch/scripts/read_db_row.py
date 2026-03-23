#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库行读取脚本
功能: 一次执行只从数据库表中读取一行数据，输出指定字段的JSON字符串
特性: 完全依赖数据库 WHERE 条件和状态更新来控制流程，无需状态文件
"""

import json
import sys
import io
from typing import List, Dict, Any

# 强制UTF-8编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("Error: 未安装 psycopg2 库，请执行: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)


class DBRowReader:
    """数据库行读取器，完全依赖数据库状态控制，无需本地状态文件"""

    def __init__(self, db_config: Dict[str, str], table_name: str,
                 select_condition: str, update_condition: str):
        """
        初始化数据库读取器

        Args:
            db_config: 数据库连接配置，包含 ip, port, db, user, password
            table_name: 输入表名（可包含 schema，如 public.table_name）
            select_condition: 筛选条件（WHERE子句，不含WHERE关键字）
            update_condition: 更新条件（SET子句，不含SET关键字）
        """
        self.db_config = db_config
        self.table_name = table_name
        self.select_condition = select_condition
        self.update_condition = update_condition
        self.primary_key = None  # 主键字段名

    def _get_primary_key(self, conn) -> str:
        """
        从数据库获取表的主键字段名

        Args:
            conn: 数据库连接对象

        Returns:
            主键字段名
        """
        if self.primary_key:
            return self.primary_key

        cursor = conn.cursor()

        # 解析 schema 和 table_name
        parts = self.table_name.split('.')
        if len(parts) == 2:
            schema_name, table_name = parts
        else:
            schema_name, table_name = 'public', self.table_name

        # 查询主键字段
        query = """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE i.indisprimary
              AND n.nspname = %s
              AND c.relname = %s
        """

        cursor.execute(query, (schema_name, table_name))
        result = cursor.fetchone()
        cursor.close()

        if not result or not result[0]:
            raise ValueError(f"表 {self.table_name} 没有定义主键")

        self.primary_key = result[0]
        return self.primary_key

    def read_next_row(self, input_table_flds: List[str]) -> Dict[str, Any]:
        """
        读取下一未读行
        通过 WHERE select_condition 查询，读取后立即 UPDATE 为 update_condition

        Args:
            input_table_flds: 需要读取的字段列表

        Returns:
            包含指定字段的字典，如果没有未读行则返回空字典
        """
        conn = None
        cursor = None

        try:
            # 建立数据库连接
            conn = psycopg2.connect(
                host=self.db_config['ip'],
                port=int(self.db_config['port']),
                database=self.db_config['db'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                connect_timeout=10
            )
            conn.autocommit = True

            # 获取主键字段名
            pk_field = self._get_primary_key(conn)

            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 构建查询SQL
            # 必须包含主键字段用于后续更新
            fields_to_select = list(set(input_table_flds) | {pk_field})
            fields_str = ', '.join(fields_to_select)

            # 构建WHERE条件（仅使用 select_condition）
            where_clause = self.select_condition if self.select_condition else '1=1'

            # 查询SQL - 使用FOR UPDATE SKIP LOCKED避免并发问题
            # 先锁定记录，防止其他进程同时读取
            query_sql = f"""
                SELECT {fields_str}
                FROM {self.table_name}
                WHERE {where_clause}
                ORDER BY {pk_field}
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """

            cursor.execute(query_sql)
            row = cursor.fetchone()

            if row is None:
                # 没有满足条件的行
                return {}

            # 将记录转换为字典
            result = dict(row)
            record_pk_value = result.get(pk_field)

            # 立即更新数据库状态（如果有更新条件）
            # 更新后，下次查询时不会再读到这条记录
            if self.update_condition and record_pk_value is not None:
                update_sql = f"""
                    UPDATE {self.table_name}
                    SET {self.update_condition}
                    WHERE {pk_field} = %s
                """
                cursor.execute(update_sql, (record_pk_value,))

            # 提取请求的字段（排除内部使用的主键）
            output = {field: result.get(field) for field in input_table_flds}

            return output

        except Exception as e:
            print(f"Error: 数据库操作失败: {str(e)}", file=sys.stderr)
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


def main():
    """主函数"""
    if len(sys.argv) < 8:
        print("使用方法: python read_db_row.py <db_ip> <db_port> <db_name> <db_user> <db_password> <table_name> <fields> [select_condition] [update_condition]")
        print()
        print("参数说明:")
        print("  db_ip, db_port, db_name, db_user, db_password - 数据库连接信息")
        print("  table_name - 表名")
        print("  fields - 需要读取的字段（逗号分隔）")
        print("  select_condition - 筛选条件（WHERE子句，不含WHERE关键字）")
        print("  update_condition - 更新条件（SET子句，不含SET关键字）")
        print()
        print("示例:")
        print('  python read_db_row.py 10.82.232.122 5432 big_poi appdeploy pass123 public.poi "id,name,poi_type" "verify_status=\'待核实\'" "verify_status=\'核实中\'"')
        sys.exit(1)

    # 解析数据库连接参数
    db_config = {
        'ip': sys.argv[1],
        'port': sys.argv[2],
        'db': sys.argv[3],
        'user': sys.argv[4],
        'password': sys.argv[5]
    }

    table_name = sys.argv[6]
    fields_str = sys.argv[7]
    select_condition = sys.argv[8] if len(sys.argv) > 8 else ""
    update_condition = sys.argv[9] if len(sys.argv) > 9 else ""

    # 解析字段列表
    input_table_flds = [f.strip() for f in fields_str.split(',')]

    try:
        reader = DBRowReader(db_config, table_name, select_condition, update_condition)
        row_data = reader.read_next_row(input_table_flds)

        if row_data:
            # 输出JSON字符串
            print(json.dumps(row_data, ensure_ascii=False))
        else:
            # 没有未读行，输出空JSON对象
            print(json.dumps({}))

    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
