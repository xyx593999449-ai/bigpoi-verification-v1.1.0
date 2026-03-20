#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本 - 帮你找出写库失败的原因
"""

import sys
import os

# 添加脚本路径
script_dir = os.path.dirname(os.path.abspath(__file__))
scripts_dir = os.path.join(script_dir, "scripts")
sys.path.insert(0, scripts_dir)

print("=" * 80)
print("质检写库技能 - 调试工具")
print("=" * 80)

# 参数配置
TASK_ID = '6bd3b59f-7081-45e2-a116-079fcc6261c4'
# 注意：这是你本地化文件所在的目录
RESULT_DIR = r'E:\wangyu\big-poi-qc\output\results'  # 改用原始字符串和反斜杠

print(f"\n📋 配置信息：")
print(f"  Task ID: {TASK_ID}")
print(f"  Result Dir: {RESULT_DIR}")
print(f"  Scripts Dir: {scripts_dir}")

# 添加路径诊断
print(f"\n🔍 路径诊断：")
from pathlib import Path
base_dir = Path(RESULT_DIR)
task_dir = base_dir / TASK_ID
index_file = task_dir / "results_index.json"
print(f"  Base Dir: {base_dir}")
print(f"  Base Dir 存在: {base_dir.exists()}")
print(f"  Task Dir: {task_dir}")
print(f"  Task Dir 存在: {task_dir.exists()}")
print(f"  Index File: {index_file}")
print(f"  Index File 存在: {index_file.exists()}")

# 列出目录内容
if task_dir.exists():
    print(f"\n  Task Dir 的文件列表：")
    for item in task_dir.iterdir():
        print(f"    - {item.name}")
else:
    print(f"\n  ⚠️  Task Dir 不存在！")

# 第一步：测试文件加载
print(f"\n{'='*80}")
print("第一步：测试从索引文件加载结果")
print(f"{'='*80}")

try:
    from file_loader import FileLoader

    loader = FileLoader()
    print(f"✓ FileLoader 导入成功")

    qc_result = loader.load_result(
        task_id=TASK_ID,
        result_dir=RESULT_DIR
    )
    print(f"✓ 成功从索引文件加载结果")
    print(f"  - qc_result.task_id: {qc_result.get('task_id')}")
    print(f"  - qc_result.qc_status: {qc_result.get('qc_status')}")
    print(f"  - qc_result.qc_score: {qc_result.get('qc_score')}")

except Exception as e:
    print(f"✗ 文件加载失败！")
    print(f"  错误类型: {type(e).__name__}")
    print(f"  错误信息: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 第二步：测试数据转换
print(f"\n{'='*80}")
print("第二步：测试数据转换")
print(f"{'='*80}")

try:
    from data_converter import DataConverter

    converter = DataConverter()
    print(f"✓ DataConverter 导入成功")

    converted_data = converter.convert(qc_result)
    print(f"✓ 数据转换成功")
    print(f"  - task_id: {converted_data.get('task_id')}")
    print(f"  - qc_status: {converted_data.get('qc_status')}")
    print(f"  - qc_score: {converted_data.get('qc_score')}")
    print(f"  - has_risk: {converted_data.get('has_risk')}")
    print(f"  - is_qualified: {converted_data.get('is_qualified')}")

except Exception as e:
    print(f"✗ 数据转换失败！")
    print(f"  错误类型: {type(e).__name__}")
    print(f"  错误信息: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 第三步：测试数据库连接
print(f"\n{'='*80}")
print("第三步：测试数据库连接")
print(f"{'='*80}")

try:
    from db_writer import QCWriter

    writer = QCWriter()
    print(f"✓ QCWriter 导入成功")
    print(f"  - 数据库配置已加载")
    print(f"  - 连接信息: {writer.db_config.get('host')}:{writer.db_config.get('port')}/{writer.db_config.get('database')}")

    writer.connect()
    print(f"✓ 数据库连接成功")

except Exception as e:
    print(f"✗ 数据库连接失败！")
    print(f"  错误类型: {type(e).__name__}")
    print(f"  错误信息: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 第四步：测试 UPDATE 操作
print(f"\n{'='*80}")
print("第四步：测试 UPDATE 操作")
print(f"{'='*80}")

try:
    print(f"  准备执行 UPDATE 语句...")
    print(f"  WHERE task_id = '{TASK_ID}'")

    result = writer.write(converted_data)

    print(f"✓ UPDATE 执行成功！")
    print(f"  - 返回结果: {result}")

except Exception as e:
    print(f"✗ UPDATE 执行失败！")
    print(f"  错误类型: {type(e).__name__}")
    print(f"  错误信息: {e}")
    import traceback
    traceback.print_exc()

finally:
    try:
        writer.close()
        print(f"\n✓ 数据库连接已关闭")
    except:
        pass

print(f"\n{'='*80}")
print("诊断完成！")
print(f"{'='*80}\n")
