#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CSV 行读取脚本
功能: 一次执行只读取CSV文件中的一行数据，输出指定字段的JSON字符串
特性: 实现已读行不再读取（通过状态文件追踪）
"""

import csv
import json
import os
import sys
import io
from pathlib import Path
from typing import List, Dict, Any

# 强制UTF-8编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class CSVRowReader:
    """CSV行读取器，支持追踪已读行"""

    def __init__(self, data_src_path: str):
        """
        初始化CSV读取器

        Args:
            data_src_path: CSV文件路径
        """
        self.csv_path = Path(data_src_path)
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV文件不存在: {data_src_path}")

        # 状态文件路径（记录已读行号）
        self.state_file = self.csv_path.parent / f".{self.csv_path.stem}_read_state.txt"

    def _get_last_read_row(self) -> int:
        """获取上次已读的行号"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        return int(content)
                    else:
                        return -1
            except (ValueError, IOError):
                return -1
        return -1

    def _update_state(self, row_number: int) -> None:
        """更新已读行号"""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            f.write(str(row_number))

    def read_next_row(self, input_table_flds: List[str]) -> Dict[str, Any]:
        """
        读取下一未读行

        Args:
            input_table_flds: 需要读取的字段列表

        Returns:
            包含指定字段的字典，如果没有未读行则返回空字典
        """
        last_read_row = self._get_last_read_row()

        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                # 验证字段是否存在
                if reader.fieldnames is None:
                    return {}

                missing_fields = set(input_table_flds) - set(reader.fieldnames)
                if missing_fields:
                    raise ValueError(f"CSV中不存在字段: {missing_fields}")

                # 跳过已读行，读取下一行
                for current_row, row in enumerate(reader):
                    if current_row > last_read_row:
                        # 提取指定字段
                        result = {field: row[field] for field in input_table_flds}

                        # 更新状态
                        self._update_state(current_row)

                        return result

        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            raise

        # 没有未读行
        return {}


def main():
    """主函数"""
    if len(sys.argv) < 3:
        print("使用方法: python read_csv_row.py <csv_path> <field1,field2,...>")
        sys.exit(1)

    csv_path = sys.argv[1]
    fields_str = sys.argv[2]

    # 解析字段列表
    input_table_flds = [f.strip() for f in fields_str.split(',')]

    try:
        reader = CSVRowReader(csv_path)
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
