#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库写入器模块。"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
import yaml
from psycopg2 import sql

try:
    from logger_config import get_logger
except ImportError:
    from .logger_config import get_logger

logger = get_logger(__name__)


class VerifiedResultWriter:
    """负责将核实结果写入 PostgreSQL。"""

    DEFAULT_INIT_TABLE = "poi_init"
    DEFAULT_VERIFIED_TABLE = "poi_verified"
    _IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(
        self,
        config_path: Optional[str] = None,
        init_table: Optional[str] = None,
        verified_table: Optional[str] = None,
    ):
        if config_path is None:
            script_dir = Path(__file__).parent
            config_path = script_dir.parent / "config" / "db_config.yaml"

        self.config_path = Path(config_path)
        self.db_config = self._load_config()
        self.conn = None
        self.init_table = init_table or self.DEFAULT_INIT_TABLE
        self.verified_table = verified_table or self.DEFAULT_VERIFIED_TABLE

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            logger.info("数据库配置加载成功: %s", self.config_path)
            return config
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件未找到: {self.config_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"配置文件格式错误: {e}")

    def connect(self):
        try:
            self.conn = psycopg2.connect(
                host=self.db_config["host"],
                port=self.db_config["port"],
                database=self.db_config["database"],
                user=self.db_config["user"],
                password=self.db_config["password"],
                connect_timeout=10,
                client_encoding="utf8",
            )
            self.conn.set_client_encoding("UTF8")
            logger.info(
                "数据库连接成功: %s:%s",
                self.db_config["host"],
                self.db_config["port"],
            )
        except psycopg2.Error as e:
            logger.error("数据库连接失败: %s", e)
            raise Exception(f"数据库连接失败: {e}")

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")

    def _split_table_name(self, table_name: str) -> Tuple[str, str]:
        if not isinstance(table_name, str) or not table_name.strip():
            raise ValueError("表名不能为空")

        parts = table_name.strip().split(".")
        if len(parts) == 1:
            schema_name, pure_table_name = "public", parts[0]
        elif len(parts) == 2:
            schema_name, pure_table_name = parts
        else:
            raise ValueError(f"非法表名: {table_name}")

        for part in (schema_name, pure_table_name):
            if not self._IDENTIFIER_PATTERN.match(part):
                raise ValueError(f"非法表名标识符: {table_name}")

        return schema_name, pure_table_name

    def _table_identifier(self, table_name: str) -> sql.Composed:
        schema_name, pure_table_name = self._split_table_name(table_name)
        return sql.Identifier(schema_name, pure_table_name)

    def _resolve_table_names(self, data: Dict[str, Any]) -> Dict[str, str]:
        init_table = data.get("init", self.init_table)
        verified_table = data.get("verified", self.verified_table)

        self._split_table_name(init_table)
        self._split_table_name(verified_table)

        return {
            "init": init_table,
            "verified": verified_table,
        }

    def _convert_to_json(self, data: Any) -> Optional[psycopg2.extras.Json]:
        if data is None:
            return None
        if isinstance(data, str):
            try:
                parsed_dict = json.loads(data)
                return psycopg2.extras.Json(parsed_dict)
            except json.JSONDecodeError:
                raise ValueError(f"JSON 字符串格式错误: {data}")
        if isinstance(data, (dict, list)):
            return psycopg2.extras.Json(data)
        raise ValueError(f"无法转换为 JSON: {type(data)}")

    def _check_task_exists(self, task_id: str, verified_table: str) -> bool:
        try:
            cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            query = sql.SQL("SELECT 1 FROM {} WHERE task_id = %s LIMIT 1").format(
                self._table_identifier(verified_table)
            )
            cursor.execute(query, (task_id,))
            result = cursor.fetchone() is not None
            cursor.close()
            return result
        except psycopg2.Error as e:
            raise Exception(f"检查 task_id 是否存在失败: {e}")

    def _validate_input(self, data: Dict[str, Any]) -> bool:
        if "index_file" not in data:
            raise ValueError("缺少必需字段: index_file")
        if not data["index_file"]:
            raise ValueError("index_file 字段不能为空")
        return True

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self._validate_input(data)
            table_names = self._resolve_table_names(data)
            return self._write_from_index_file(data["index_file"], table_names)
        except Exception as e:
            logger.error("写入失败: %s", e)
            return {
                "success": False,
                "error": str(e),
            }

    def _write_from_index_file(self, index_file_path: str, table_names: Dict[str, str]) -> Dict[str, Any]:
        from file_loader import FileLoader
        from data_converter import DataConverter

        loader = FileLoader()
        converter = DataConverter()

        all_data = loader.load_all_from_index(index_file_path, load_evidence=True, load_record=True)

        index_data = all_data["index"]
        decision = all_data["decision"]
        evidence = all_data.get("evidence", [])
        record = all_data.get("record", {})

        if record and "verification_result" in record and "final_values" in record["verification_result"]:
            logger.info("从 record.verification_result.final_values 中提取核实后的 POI 信息")
            final_values = record["verification_result"]["final_values"]
            coordinates = final_values.get("coordinates", {})
            poi_data = {
                "id": record.get("poi_id", index_data.get("poi_id", "")),
                "name": final_values.get("name", ""),
                "x_coord": coordinates.get("longitude"),
                "y_coord": coordinates.get("latitude"),
                "poi_type": final_values.get("category"),
                "address": final_values.get("address"),
                "city": final_values.get("city"),
                "city_adcode": final_values.get("city_adcode", ""),
            }
            if not poi_data["city_adcode"] and "input_data" in record:
                poi_data["city_adcode"] = record["input_data"].get("city_adcode", "")
        elif record and "input_data" in record:
            logger.info("从 record.input_data 中提取 POI 基础信息")
            input_data = record["input_data"]
            coordinates = input_data.get("coordinates", {})
            poi_data = {
                "id": record.get("poi_id", index_data.get("poi_id", "")),
                "name": input_data.get("name", ""),
                "x_coord": coordinates.get("longitude"),
                "y_coord": coordinates.get("latitude"),
                "poi_type": input_data.get("poi_type"),
                "address": input_data.get("address"),
                "city": input_data.get("city"),
                "city_adcode": input_data.get("city_adcode", ""),
            }
        elif "poi_data" in index_data:
            logger.info("从索引文件的 poi_data 中提取 POI 基础信息")
            poi_data = index_data["poi_data"]
        else:
            logger.warning("未找到 POI 基础信息，使用空字典")
            poi_data = {
                "id": index_data.get("poi_id", ""),
                "name": "",
                "x_coord": None,
                "y_coord": None,
                "poi_type": None,
                "address": "",
                "city": "",
                "city_adcode": "",
            }

        task_id = index_data.get("task_id", "")
        db_data = converter.decision_to_db_format(decision, evidence, poi_data, task_id=task_id, record=record)
        return self._execute_db_write(db_data, table_names)

    def _execute_db_write(self, db_data: Dict[str, Any], table_names: Dict[str, str]) -> Dict[str, Any]:
        task_id = db_data["task_id"]
        poi_id = db_data["id"]
        init_table = table_names["init"]
        verified_table = table_names["verified"]

        logger.info(
            "开始写入核实结果: task_id=%s, poi_id=%s, init=%s, verified=%s",
            task_id,
            poi_id,
            init_table,
            verified_table,
        )

        task_exists = self._check_task_exists(task_id, verified_table)
        if task_exists:
            logger.warning("task_id %s 已存在于成果表中，仅更新原始表状态", task_id)

        current_time = datetime.now()
        cursor = self.conn.cursor()
        try:
            if not task_exists:
                verify_info_json = self._convert_to_json(db_data.get("verify_info"))
                evidence_record_json = self._convert_to_json(db_data.get("evidence_record"))
                changes_made_json = self._convert_to_json(db_data.get("changes_made"))

                insert_sql = sql.SQL(
                    """
                    INSERT INTO {} (
                        task_id, id, name, x_coord, y_coord, poi_type, address, city, city_adcode,
                        verify_status, verify_result, overall_confidence, poi_status,
                        original_task_id, original_id,
                        verify_info, evidence_record, changes_made, verification_notes,
                        verify_time, updatetime, verified_by, verification_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """
                ).format(self._table_identifier(verified_table))

                cursor.execute(
                    insert_sql,
                    (
                        task_id,
                        db_data["id"],
                        db_data.get("name", ""),
                        db_data.get("x_coord"),
                        db_data.get("y_coord"),
                        db_data.get("poi_type"),
                        db_data.get("address"),
                        db_data.get("city"),
                        db_data.get("city_adcode"),
                        db_data.get("verify_status", "已核实"),
                        db_data["verify_result"],
                        db_data.get("overall_confidence"),
                        db_data.get("poi_status", 1),
                        task_id,
                        db_data["id"],
                        verify_info_json,
                        evidence_record_json,
                        changes_made_json,
                        db_data.get("verification_notes"),
                        current_time,
                        current_time,
                        "system",
                        "1.4.0",
                    ),
                )

            update_sql = sql.SQL(
                "UPDATE {} SET verify_status = %s, updatetime = %s WHERE task_id = %s"
            ).format(self._table_identifier(init_table))
            cursor.execute(update_sql, ("已核实", current_time, task_id))

            if cursor.rowcount == 0:
                logger.warning("原始表未找到 task_id=%s 的记录，可能已被删除", task_id)

            self.conn.commit()
            logger.info("核实结果写入成功: task_id=%s", task_id)

            return {
                "success": True,
                "task_id": task_id,
                "poi_id": poi_id,
                "message": "POI 核实结果已存在，原始表状态已更新"
                if task_exists
                else "POI 核实结果已成功写入成果表",
                "tables_updated": [init_table] if task_exists else [verified_table, init_table],
                "verify_time": current_time.isoformat(),
                "skipped": task_exists,
            }
        except Exception as e:
            self.conn.rollback()
            logger.error("数据库操作失败: %s", e)
            raise
        finally:
            cursor.close()

    def write_batch(self, data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        success_count = 0
        failure_count = 0
        skipped_count = 0
        errors = []

        for idx, data in enumerate(data_list):
            try:
                result = self.write(data)
                if result.get("success"):
                    if result.get("skipped"):
                        skipped_count += 1
                    else:
                        success_count += 1
                else:
                    failure_count += 1
                    errors.append(
                        {
                            "index": idx,
                            "task_id": data.get("task_id") or data.get("index_file", "unknown"),
                            "error": result.get("error", "未知错误"),
                        }
                    )
            except Exception as e:
                failure_count += 1
                errors.append(
                    {
                        "index": idx,
                        "task_id": data.get("task_id") or data.get("index_file", "unknown"),
                        "error": str(e),
                    }
                )

        return {
            "success": failure_count == 0,
            "total": len(data_list),
            "success_count": success_count,
            "failure_count": failure_count,
            "skipped_count": skipped_count,
            "errors": errors if errors else None,
        }


def main():
    if len(sys.argv) < 2:
        print("用法: python -m scripts.db_writer <index_file_path>")
        print("示例: python -m scripts.db_writer output/results/TASK_20260227_001/index.json")
        sys.exit(1)

    writer = None
    try:
        writer = VerifiedResultWriter()
        writer.connect()

        index_file = sys.argv[1]
        test_data = {"index_file": index_file}

        result = writer.write(test_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if writer:
            writer.close()


if __name__ == "__main__":
    main()
