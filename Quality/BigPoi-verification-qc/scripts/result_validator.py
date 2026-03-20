#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果校验脚本 - 验证 BigPOI 质检结果的有效性

校验范围：
1. JSON Schema 验证
2. 维度结构与字段完整性检查
3. 评分规则反算校验
4. 状态、风险维度、统计标记一致性检查
5. 结果文件与命名规范检查
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Optional, List, Tuple, Any

try:
    import jsonschema
    from jsonschema import Draft7Validator, RefResolver
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None
    Draft7Validator = None
    RefResolver = None


CORE_DIMENSIONS = (
    'existence',
    'name',
    'location',
    'address',
    'administrative',
    'category',
)
ALL_DIMENSIONS = CORE_DIMENSIONS + ('downgrade_consistency',)
RULE_IDS = {'R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7'}
FILE_PATTERN = re.compile(
    r'^(?P<timestamp>\d{8}_\d{6})_(?P<task_id>.+)\.(?P<file_type>complete|summary|results_index)\.json$'
)


class ResultValidator:
    """质检结果校验器"""

    def __init__(
        self,
        schema_path: str = './schema/qc_result.schema.json',
        scoring_policy_path: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.schema_path = Path(schema_path)
        self.logger = logger or logging.getLogger(__name__)
        self.schema = self._load_json(self.schema_path)

        schema_dir = self.schema_path.parent
        self.summary_schema = self._load_json(schema_dir / 'qc_summary.schema.json')
        self.index_schema = self._load_json(schema_dir / 'qc_results_index.schema.json')

        if scoring_policy_path is None:
            scoring_policy_path = str(self.schema_path.parent.parent / 'config' / 'scoring_policy.json')
        self.scoring_policy_path = Path(scoring_policy_path)
        self.scoring_policy = self._load_json(self.scoring_policy_path)

    def _load_json(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            self.logger.warning(f"JSON 文件不存在：{path}")
            return None
        except Exception as exc:
            self.logger.error(f"加载 JSON 文件失败 {path}: {exc}")
            return None

    def validate(self, qc_result: Dict, result_dir: Optional[str] = None) -> Dict:
        errors: List[str] = []
        warnings: List[str] = []
        details = {
            'schema_validation': {},
            'file_validation': {},
            'naming_validation': {},
        }

        try:
            schema_errors, schema_warnings = self._validate_schema(qc_result)
            errors.extend(schema_errors)
            warnings.extend(schema_warnings)
            details['schema_validation'] = {
                'is_valid': len(schema_errors) == 0,
                'errors': schema_errors,
                'warnings': schema_warnings,
            }

            if result_dir:
                file_errors, file_warnings = self._validate_files(result_dir, qc_result.get('task_id'))
                errors.extend(file_errors)
                warnings.extend(file_warnings)
                details['file_validation'] = {
                    'is_valid': len(file_errors) == 0,
                    'errors': file_errors,
                    'warnings': file_warnings,
                }

                naming_errors, naming_warnings = self._validate_naming(result_dir, qc_result.get('task_id'))
                errors.extend(naming_errors)
                warnings.extend(naming_warnings)
                details['naming_validation'] = {
                    'is_valid': len(naming_errors) == 0,
                    'errors': naming_errors,
                    'warnings': naming_warnings,
                }

            is_valid = len(errors) == 0
            status = 'valid' if is_valid else ('partial' if len(errors) < 3 else 'invalid')
            return {
                'is_valid': is_valid,
                'status': status,
                'errors': errors,
                'warnings': warnings,
                'details': details,
            }
        except Exception as exc:
            error_msg = f"校验过程发生异常：{exc}"
            self.logger.error(error_msg, exc_info=True)
            return {
                'is_valid': False,
                'status': 'invalid',
                'errors': [error_msg],
                'warnings': warnings,
                'details': details,
            }

    def _validate_schema(self, qc_result: Dict) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        errors.extend(self._run_jsonschema_validation(qc_result, self.schema, self.schema_path, 'qc_result'))
        if self.schema and jsonschema is None:
            warnings.append('jsonschema 未安装，Schema 校验仅执行手工校验')

        errors.extend(self._validate_top_level(qc_result))
        return errors, warnings

    def _run_jsonschema_validation(
        self,
        payload: Dict,
        schema: Optional[Dict],
        schema_path: Path,
        label: str,
    ) -> List[str]:
        if not schema or Draft7Validator is None or RefResolver is None:
            return []

        try:
            resolver = RefResolver(base_uri=schema_path.resolve().as_uri(), referrer=schema)
            validator = Draft7Validator(schema, resolver=resolver)
            return [
                f"{label} Schema 校验失败：{'/'.join(map(str, error.absolute_path)) or '<root>'} -> {error.message}"
                for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
            ]
        except Exception as exc:
            return [f"{label} Schema 校验器执行失败：{exc}"]

    def _validate_top_level(self, qc_result: Dict) -> List[str]:
        errors: List[str] = []

        required_fields = [
            'task_id',
            'qc_status',
            'qc_score',
            'has_risk',
            'risk_dims',
            'triggered_rules',
            'dimension_results',
            'explanation',
            'statistics_flags',
        ]
        for field in required_fields:
            if field not in qc_result:
                errors.append(f"缺少必需字段：{field}")

        dimension_results = qc_result.get('dimension_results')
        if not isinstance(dimension_results, dict):
            errors.append('dimension_results 必须是对象')
            return errors

        missing_dims = [dim for dim in ALL_DIMENSIONS if dim not in dimension_results]
        if missing_dims:
            errors.append(f"dimension_results 缺少维度：{missing_dims}")
            return errors

        for dim_name in ALL_DIMENSIONS:
            dim_result = dimension_results.get(dim_name)
            if dim_name == 'downgrade_consistency':
                errors.extend(self._validate_downgrade_consistency(dim_result))
            else:
                errors.extend(self._validate_core_dimension(dim_name, dim_result))

        errors.extend(self._validate_triggered_rules(qc_result.get('triggered_rules', [])))
        errors.extend(self._check_logical_consistency(qc_result))
        return errors

    def _validate_core_dimension(self, dim_name: str, dim_result: Any) -> List[str]:
        errors: List[str] = []

        if not isinstance(dim_result, dict):
            return [f"维度 {dim_name} 的结果必须是对象"]

        for field in ['status', 'risk_level', 'explanation', 'evidence']:
            if field not in dim_result:
                errors.append(f"维度 {dim_name} 缺少字段：{field}")

        status = dim_result.get('status')
        risk_level = dim_result.get('risk_level')
        evidence = dim_result.get('evidence')
        related_rules = dim_result.get('related_rules', [])

        if status not in ['pass', 'risk', 'fail']:
            errors.append(f"维度 {dim_name} 的 status 无效：{status}")

        if status == 'pass' and risk_level != 'none':
            errors.append(f"维度 {dim_name} 为 pass 时 risk_level 必须是 none")
        elif status == 'risk' and risk_level not in ['low', 'medium', 'high']:
            errors.append(f"维度 {dim_name} 为 risk 时 risk_level 必须为 low/medium/high")
        elif status == 'fail' and risk_level != 'high':
            errors.append(f"维度 {dim_name} 为 fail 时 risk_level 必须是 high")

        if not isinstance(evidence, list):
            errors.append(f"维度 {dim_name} 的 evidence 必须是数组")
        elif status in ['pass', 'risk'] and len(evidence) == 0:
            errors.append(f"维度 {dim_name} 为 {status} 时 evidence 不能为空数组")

        if not isinstance(related_rules, list):
            errors.append(f"维度 {dim_name} 的 related_rules 必须是数组")
        else:
            invalid_rules = [rule_id for rule_id in related_rules if rule_id not in RULE_IDS]
            if invalid_rules:
                errors.append(f"维度 {dim_name} 的 related_rules 含无效规则：{invalid_rules}")

        confidence = dim_result.get('confidence')
        if confidence is not None and not self._is_probability(confidence):
            errors.append(f"维度 {dim_name} 的 confidence 必须在 0-1 范围内")

        return errors

    def _validate_downgrade_consistency(self, dim_result: Any) -> List[str]:
        errors: List[str] = []

        if not isinstance(dim_result, dict):
            return ['维度 downgrade_consistency 的结果必须是对象']

        required_fields = [
            'status',
            'risk_level',
            'explanation',
            'is_consistent',
            'issue_type',
            'qc_manual_review_required',
            'upstream_manual_review_required',
            'evidence',
        ]
        for field in required_fields:
            if field not in dim_result:
                errors.append(f"维度 downgrade_consistency 缺少字段：{field}")

        status = dim_result.get('status')
        risk_level = dim_result.get('risk_level')
        is_consistent = dim_result.get('is_consistent')
        issue_type = dim_result.get('issue_type')

        if status not in ['pass', 'risk', 'fail']:
            errors.append(f"维度 downgrade_consistency 的 status 无效：{status}")

        if status == 'pass' and risk_level != 'none':
            errors.append('downgrade_consistency 为 pass 时 risk_level 必须是 none')
        elif status == 'risk' and risk_level not in ['low', 'medium', 'high']:
            errors.append('downgrade_consistency 为 risk 时 risk_level 必须为 low/medium/high')
        elif status == 'fail' and risk_level != 'high':
            errors.append('downgrade_consistency 为 fail 时 risk_level 必须是 high')

        if issue_type not in ['consistent', 'missed_downgrade', 'unnecessary_downgrade']:
            errors.append(f"downgrade_consistency 的 issue_type 无效：{issue_type}")

        if not isinstance(dim_result.get('evidence'), list):
            errors.append('downgrade_consistency 的 evidence 必须是数组')

        qc_manual = dim_result.get('qc_manual_review_required')
        upstream_manual = dim_result.get('upstream_manual_review_required')
        if not isinstance(qc_manual, bool):
            errors.append('downgrade_consistency.qc_manual_review_required 必须是布尔值')
        if not isinstance(upstream_manual, bool):
            errors.append('downgrade_consistency.upstream_manual_review_required 必须是布尔值')
        if not isinstance(is_consistent, bool):
            errors.append('downgrade_consistency.is_consistent 必须是布尔值')

        if isinstance(qc_manual, bool) and isinstance(upstream_manual, bool) and isinstance(is_consistent, bool):
            expected_consistent = qc_manual == upstream_manual
            if is_consistent != expected_consistent:
                errors.append(
                    'downgrade_consistency.is_consistent 与 qc/upstream manual review 标志不一致'
                )
            if expected_consistent and status != 'pass':
                errors.append('当 QC 与上游人工核实判断一致时，downgrade_consistency.status 应为 pass')
            if not expected_consistent and status == 'pass':
                errors.append('当 QC 与上游人工核实判断不一致时，downgrade_consistency.status 不能为 pass')
            if not expected_consistent:
                expected_issue = 'missed_downgrade' if qc_manual and not upstream_manual else 'unnecessary_downgrade'
                if issue_type != expected_issue:
                    errors.append(
                        f"downgrade_consistency.issue_type 应为 {expected_issue}，实际为 {issue_type}"
                    )
            elif issue_type != 'consistent':
                errors.append('downgrade_consistency 一致时 issue_type 必须为 consistent')

        related_rules = dim_result.get('related_rules', [])
        if related_rules and related_rules != ['R7']:
            errors.append('downgrade_consistency.related_rules 只能包含 R7')

        confidence = dim_result.get('confidence')
        if confidence is not None and not self._is_probability(confidence):
            errors.append('downgrade_consistency.confidence 必须在 0-1 范围内')

        return errors

    def _validate_triggered_rules(self, triggered_rules: Any) -> List[str]:
        errors: List[str] = []
        if not isinstance(triggered_rules, list):
            return ['triggered_rules 必须是数组']

        for index, rule in enumerate(triggered_rules):
            if not isinstance(rule, dict):
                errors.append(f"triggered_rules[{index}] 必须是对象")
                continue
            for field in ['rule_id', 'rule_name', 'dimension']:
                if field not in rule:
                    errors.append(f"triggered_rules[{index}] 缺少字段：{field}")
            if rule.get('rule_id') not in RULE_IDS:
                errors.append(f"triggered_rules[{index}] 的 rule_id 无效：{rule.get('rule_id')}")
            if rule.get('dimension') not in ALL_DIMENSIONS:
                errors.append(
                    f"triggered_rules[{index}] 的 dimension 无效：{rule.get('dimension')}"
                )
        return errors

    def _check_logical_consistency(self, qc_result: Dict) -> List[str]:
        errors: List[str] = []
        dimension_results = qc_result.get('dimension_results', {})

        has_core_fail = any(
            dimension_results.get(dim, {}).get('status') == 'fail' for dim in CORE_DIMENSIONS
        )
        has_core_risk = any(
            dimension_results.get(dim, {}).get('status') == 'risk' for dim in CORE_DIMENSIONS
        )
        consistency_status = dimension_results.get('downgrade_consistency', {}).get('status')

        expected_status = 'qualified'
        if has_core_fail:
            expected_status = 'unqualified'
        elif has_core_risk or consistency_status in ['risk', 'fail']:
            expected_status = 'risky'

        if qc_result.get('qc_status') != expected_status:
            errors.append(
                f"qc_status 与维度状态不一致，预期 {expected_status}，实际 {qc_result.get('qc_status')}"
            )

        actual_risk_dims = sorted(
            [dim for dim in ALL_DIMENSIONS if dimension_results.get(dim, {}).get('status') in ['risk', 'fail']]
        )
        listed_risk_dims = sorted(qc_result.get('risk_dims', []))
        if actual_risk_dims != listed_risk_dims:
            errors.append(
                f"risk_dims 列表与实际风险维度不一致。实际：{actual_risk_dims}，列表：{listed_risk_dims}"
            )

        has_risk_actual = len(actual_risk_dims) > 0
        if qc_result.get('has_risk') != has_risk_actual:
            errors.append(
                f"has_risk 与维度状态不一致。实际应为 {has_risk_actual}，输出为 {qc_result.get('has_risk')}"
            )

        expected_score = self._calculate_expected_score(dimension_results)
        if qc_result.get('qc_score') != expected_score:
            errors.append(
                f"qc_score 与评分策略不一致。预期 {expected_score}，实际 {qc_result.get('qc_score')}"
            )

        errors.extend(self._validate_statistics_flags(qc_result, expected_status, has_core_fail, has_core_risk))
        return errors

    def _validate_statistics_flags(
        self,
        qc_result: Dict,
        expected_status: str,
        has_core_fail: bool,
        has_core_risk: bool,
    ) -> List[str]:
        errors: List[str] = []
        flags = qc_result.get('statistics_flags')
        if not isinstance(flags, dict):
            return ['statistics_flags 必须是对象']

        consistency_result = qc_result.get('dimension_results', {}).get('downgrade_consistency', {})
        qc_manual = has_core_fail or has_core_risk
        upstream_manual = consistency_result.get('upstream_manual_review_required')
        issue_type = consistency_result.get('issue_type')

        expected_flags = {
            'is_qualified': expected_status == 'qualified',
            'is_auto_approvable': expected_status == 'qualified',
            'is_manual_required': expected_status != 'qualified',
            'qc_manual_review_required': qc_manual,
            'upstream_manual_review_required': upstream_manual,
            'downgrade_issue_type': issue_type,
        }

        for key, expected_value in expected_flags.items():
            if flags.get(key) != expected_value:
                errors.append(
                    f"statistics_flags.{key} 与预期不一致。预期 {expected_value}，实际 {flags.get(key)}"
                )

        return errors

    def _calculate_expected_score(self, dimension_results: Dict[str, Dict[str, Any]]) -> int:
        if not self.scoring_policy:
            return 0

        weights = self.scoring_policy.get('dimension_weights', {})
        factors = self.scoring_policy.get('status_factors', {})
        pass_factor = factors.get('pass', 1.0)
        risk_factors = factors.get('risk', {})
        fail_factor = factors.get('fail', 0.0)

        total = 0.0
        for dim_name, weight in weights.items():
            result = dimension_results.get(dim_name, {})
            status = result.get('status')
            risk_level = result.get('risk_level')

            if status == 'pass':
                factor = pass_factor
            elif status == 'risk':
                factor = risk_factors.get(risk_level, 0.0)
            elif status == 'fail':
                factor = fail_factor
            else:
                factor = 0.0

            total += float(weight) * float(factor)

        return int(round(total))

    def _validate_files(self, result_dir: str, task_id: Optional[str]) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []
        result_path = Path(result_dir)

        if not result_path.exists():
            return [f"结果目录不存在：{result_dir}"], warnings

        files_found = {'complete': [], 'summary': [], 'results_index': []}

        for file_path in result_path.glob('*.json'):
            match = FILE_PATTERN.match(file_path.name)
            if match:
                file_task_id = match.group('task_id')
                if task_id and file_task_id != task_id:
                    errors.append(f"文件 {file_path.name} 的 task_id 与结果不一致：{file_task_id} != {task_id}")
                files_found[match.group('file_type')].append(file_path)
            elif file_path.name != 'results_index.json':
                warnings.append(f"发现不符合时间戳命名规范的 JSON 文件：{file_path.name}")

        for file_type, schema in [
            ('complete', self.schema),
            ('summary', self.summary_schema),
            ('results_index', self.index_schema),
        ]:
            if not files_found[file_type]:
                errors.append(f"缺少必需的文件类型：{file_type}.json")
                continue

            for file_path in files_found[file_type]:
                errors.extend(self._validate_json_file(file_path, schema, file_type))

        stable_index_path = result_path / 'results_index.json'
        if stable_index_path.exists():
            errors.extend(self._validate_json_file(stable_index_path, self.index_schema, 'results_index(stable)'))

        return errors, warnings

    def _validate_json_file(self, file_path: Path, schema: Optional[Dict], label: str) -> List[str]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except Exception as exc:
            return [f"读取 {label} 文件失败 {file_path.name}: {exc}"]

        return self._run_jsonschema_validation(payload, schema, self._schema_path_for_label(label), file_path.name)

    def _schema_path_for_label(self, label: str) -> Path:
        schema_dir = self.schema_path.parent
        if label.startswith('summary'):
            return schema_dir / 'qc_summary.schema.json'
        if label.startswith('results_index'):
            return schema_dir / 'qc_results_index.schema.json'
        return self.schema_path

    def _validate_naming(self, result_dir: str, task_id: Optional[str]) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []
        result_path = Path(result_dir)

        if task_id and result_path.name != task_id:
            errors.append(f"结果目录名应为 task_id。实际目录名：{result_path.name}，task_id：{task_id}")

        for file_path in result_path.glob('*.json'):
            if file_path.name == 'results_index.json':
                continue

            match = FILE_PATTERN.match(file_path.name)
            if not match:
                errors.append(
                    f"文件名 '{file_path.name}' 不符合规范，应为 YYYYMMDD_HHmmss_<task_id>.<type>.json"
                )
                continue

            if task_id and match.group('task_id') != task_id:
                errors.append(f"文件名 '{file_path.name}' 中的 task_id 与结果不一致")

        return errors, warnings

    @staticmethod
    def _is_probability(value: Any) -> bool:
        return isinstance(value, (int, float)) and 0 <= float(value) <= 1


if __name__ == '__main__':
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    logger = logging.getLogger(__name__)

    script_dir = Path(__file__).parent

    parser = argparse.ArgumentParser(description='验证 BigPOI 质检结果的有效性')
    parser.add_argument('result_json', type=str, help='质检结果 JSON 文件路径')
    parser.add_argument('--result-dir', type=str, default=None, help='结果目录路径')
    parser.add_argument('--schema-dir', type=str, default=None, help='Schema 目录路径')
    parser.add_argument(
        '--scoring-policy',
        type=str,
        default=None,
        help='评分策略 JSON 文件路径（默认使用 ../config/scoring_policy.json）',
    )
    parser.add_argument(
        '--output-format',
        type=str,
        choices=['json', 'text'],
        default='json',
        help='输出格式',
    )

    args = parser.parse_args()

    result_file = Path(args.result_json)
    if not result_file.exists():
        logger.error(f"质检结果文件不存在：{args.result_json}")
        sys.exit(1)

    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            qc_result = json.load(f)
    except Exception as exc:
        logger.error(f"读取质检结果失败：{exc}")
        sys.exit(1)

    schema_dir = Path(args.schema_dir) if args.schema_dir else script_dir.parent / 'schema'
    schema_path = schema_dir / 'qc_result.schema.json'

    validator = ResultValidator(
        schema_path=str(schema_path),
        scoring_policy_path=args.scoring_policy,
        logger=logger,
    )
    validation_result = validator.validate(qc_result, result_dir=args.result_dir)

    if args.output_format == 'json':
        print(json.dumps(validation_result, ensure_ascii=False, indent=2))
    else:
        print('=' * 60)
        print('BigPOI 质检结果验证报告')
        print('=' * 60)
        print(f"整体状态：{validation_result['status']}")
        print(f"是否有效：{'是' if validation_result['is_valid'] else '否'}")
        print(f"错误数量：{len(validation_result['errors'])}")
        for index, error in enumerate(validation_result['errors'], 1):
            print(f"  {index}. {error}")
        print(f"警告数量：{len(validation_result['warnings'])}")
        for index, warning in enumerate(validation_result['warnings'], 1):
            print(f"  {index}. {warning}")
