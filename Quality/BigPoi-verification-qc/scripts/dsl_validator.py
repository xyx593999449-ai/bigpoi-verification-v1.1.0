#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSL 校验脚本 - 验证 BigPOI 质检规则 DSL 的结构完整性和关键执行约束。
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import jsonschema
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None
    Draft7Validator = None


DIMENSION_RULE_MAP = {
    'existence': 'R1',
    'name': 'R2',
    'location': 'R3',
    'address': 'R4',
    'administrative': 'R5',
    'category': 'R6',
    'downgrade_consistency': 'R7',
}
EXPECTED_WORKFLOW = [
    'integrity_check',
    'normalize_record_and_evidence',
    'compute_dimension_metrics',
    'evaluate_dimension_outcomes',
    'derive_manual_review_flags',
    'evaluate_downgrade_consistency',
    'calculate_score',
    'aggregate_result',
]
EXPECTED_NORMALIZATION_PROFILES = {'name', 'address', 'administrative', 'category'}
EXPECTED_DERIVED_FIELDS = {
    'qc_manual_review_required',
    'upstream_manual_review_signal_source',
    'upstream_manual_review_required',
}
COMPARISON_OPS = {'eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'in', 'not_in', 'between', 'exists'}
STATUS_RANK = {'fail': 0, 'risk': 1, 'pass': 2}


class DslValidator:
    """规则 DSL 校验器"""

    def __init__(
        self,
        dsl_path: str = './rules/decision_tables.json',
        schema_path: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.dsl_path = Path(dsl_path)
        self.logger = logger or logging.getLogger(__name__)
        self.dsl = self._load_json(self.dsl_path)

        if schema_path is None:
            schema_path = str(self.dsl_path.parent.parent / 'schema' / 'decision_tables.schema.json')
        self.schema_path = Path(schema_path)
        self.schema = self._load_json(self.schema_path)

    def _load_json(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as handle:
                    return json.load(handle)
            self.logger.warning(f'JSON 文件不存在：{path}')
            return None
        except Exception as exc:
            self.logger.error(f'加载 JSON 文件失败 {path}: {exc}')
            return None

    def validate(self) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        details: Dict[str, Any] = {
            'schema_validation': {},
            'manual_validation': {},
        }

        if self.dsl is None:
            errors.append(f'无法加载 DSL 文件：{self.dsl_path}')
        if self.schema is None:
            errors.append(f'无法加载 DSL Schema 文件：{self.schema_path}')

        if errors:
            return {
                'is_valid': False,
                'status': 'invalid',
                'errors': errors,
                'warnings': warnings,
                'details': details,
            }

        schema_errors, schema_warnings = self._validate_schema()
        errors.extend(schema_errors)
        warnings.extend(schema_warnings)
        details['schema_validation'] = {
            'is_valid': len(schema_errors) == 0,
            'errors': schema_errors,
            'warnings': schema_warnings,
        }

        manual_errors = self._validate_manual()
        errors.extend(manual_errors)
        details['manual_validation'] = {
            'is_valid': len(manual_errors) == 0,
            'errors': manual_errors,
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

    def _validate_schema(self) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        if Draft7Validator is None:
            warnings.append('jsonschema 未安装，DSL Schema 校验仅执行手工校验')
            return errors, warnings

        try:
            validator = Draft7Validator(self.schema)
            errors.extend(
                [
                    f"decision_tables DSL Schema 校验失败：{'/'.join(map(str, error.absolute_path)) or '<root>'} -> {error.message}"
                    for error in sorted(validator.iter_errors(self.dsl), key=lambda err: list(err.absolute_path))
                ]
            )
        except Exception as exc:
            errors.append(f'DSL Schema 校验器执行失败：{exc}')

        return errors, warnings

    def _validate_manual(self) -> List[str]:
        errors: List[str] = []

        errors.extend(self._validate_top_level())
        errors.extend(self._validate_integrity_check())
        errors.extend(self._validate_source_priority_profiles())
        errors.extend(self._validate_normalization_profiles())
        errors.extend(self._validate_derived_fields())
        errors.extend(self._validate_dimensions())
        return errors

    def _validate_top_level(self) -> List[str]:
        errors: List[str] = []

        if self.dsl.get('execution_model') != 'deterministic_rule_dsl':
            errors.append('execution_model 必须是 deterministic_rule_dsl')

        workflow = self.dsl.get('workflow')
        if workflow != EXPECTED_WORKFLOW:
            errors.append(f'workflow 必须严格等于 {EXPECTED_WORKFLOW}')

        return errors

    def _validate_integrity_check(self) -> List[str]:
        errors: List[str] = []
        integrity = self.dsl.get('integrity_check')
        if not isinstance(integrity, dict):
            return ['integrity_check 必须是对象']

        if integrity.get('minimum_evidence_count', 0) < 1:
            errors.append('integrity_check.minimum_evidence_count 必须 >= 1')

        on_failure = integrity.get('on_failure')
        if not isinstance(on_failure, dict):
            return errors + ['integrity_check.on_failure 必须是对象']

        if on_failure.get('dimension_status') != 'fail':
            errors.append('integrity_check.on_failure.dimension_status 必须是 fail')
        if on_failure.get('risk_level') != 'high':
            errors.append('integrity_check.on_failure.risk_level 必须是 high')
        if on_failure.get('qc_status') != 'unqualified':
            errors.append('integrity_check.on_failure.qc_status 必须是 unqualified')
        if on_failure.get('qc_score') != 0:
            errors.append('integrity_check.on_failure.qc_score 必须是 0')

        dimension_impacts = on_failure.get('dimension_impacts')
        if not isinstance(dimension_impacts, dict):
            errors.append('integrity_check.on_failure.dimension_impacts 必须是对象')
        else:
            allowed_dimensions = set(DIMENSION_RULE_MAP)
            for field_name, impacts in dimension_impacts.items():
                if not isinstance(impacts, list) or not impacts:
                    errors.append(f'integrity_check.on_failure.dimension_impacts[{field_name}] 必须是非空数组')
                    continue
                invalid = [dimension for dimension in impacts if dimension not in allowed_dimensions]
                if invalid:
                    errors.append(f'integrity_check.on_failure.dimension_impacts[{field_name}] 含无效维度：{invalid}')

        return errors

    def _validate_source_priority_profiles(self) -> List[str]:
        errors: List[str] = []
        profiles = self.dsl.get('source_priority_profiles')
        if not isinstance(profiles, dict):
            return ['source_priority_profiles 必须是对象']

        default_profile = profiles.get('default')
        if not isinstance(default_profile, list) or not default_profile:
            return ['source_priority_profiles.default 必须是非空数组']

        priorities = []
        has_authoritative = False
        for index, item in enumerate(default_profile):
            if not isinstance(item, dict):
                errors.append(f'source_priority_profiles.default[{index}] 必须是对象')
                continue
            priority = item.get('priority')
            if not isinstance(priority, int) or priority < 1:
                errors.append(f'source_priority_profiles.default[{index}].priority 必须是正整数')
            else:
                priorities.append(priority)
            if item.get('authoritative') is True:
                has_authoritative = True

        if len(priorities) != len(set(priorities)):
            errors.append('source_priority_profiles.default.priority 不允许重复')
        if not has_authoritative:
            errors.append('source_priority_profiles.default 至少需要一条 authoritative = true')

        return errors

    def _validate_normalization_profiles(self) -> List[str]:
        errors: List[str] = []
        profiles = self.dsl.get('normalization_profiles')
        if not isinstance(profiles, dict):
            return ['normalization_profiles 必须是对象']

        missing = sorted(EXPECTED_NORMALIZATION_PROFILES - set(profiles))
        if missing:
            errors.append(f'normalization_profiles 缺少：{missing}')
        return errors

    def _validate_derived_fields(self) -> List[str]:
        errors: List[str] = []
        derived_fields = self.dsl.get('derived_fields')
        if not isinstance(derived_fields, dict):
            return ['derived_fields 必须是对象']

        missing = sorted(EXPECTED_DERIVED_FIELDS - set(derived_fields))
        if missing:
            errors.append(f'derived_fields 缺少：{missing}')

        for field_name in EXPECTED_DERIVED_FIELDS & set(derived_fields):
            field = derived_fields[field_name]
            if not isinstance(field, dict):
                errors.append(f'derived_fields.{field_name} 必须是对象')
                continue
            errors.extend(self._validate_derived_field(field_name, field))

        return errors

    def _validate_derived_field(self, field_name: str, field: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        if 'expression' not in field and 'resolution_order' not in field:
            errors.append(f'derived_fields.{field_name} 必须至少包含 expression 或 resolution_order')
        if 'expression' in field:
            errors.extend(self._validate_condition(field['expression'], f'derived_fields.{field_name}.expression'))
        if 'resolution_order' in field:
            resolution_order = field['resolution_order']
            if not isinstance(resolution_order, list) or not resolution_order:
                errors.append(f'derived_fields.{field_name}.resolution_order 必须是非空数组')
            else:
                for index, item in enumerate(resolution_order):
                    if not isinstance(item, dict):
                        errors.append(f'derived_fields.{field_name}.resolution_order[{index}] 必须是对象')
                        continue
                    errors.extend(
                        self._validate_condition(
                            item.get('when'),
                            f'derived_fields.{field_name}.resolution_order[{index}].when',
                        )
                    )
        return errors

    def _validate_dimensions(self) -> List[str]:
        errors: List[str] = []
        dimensions = self.dsl.get('dimensions')
        if not isinstance(dimensions, dict):
            return ['dimensions 必须是对象']

        missing = sorted(set(DIMENSION_RULE_MAP) - set(dimensions))
        extra = sorted(set(dimensions) - set(DIMENSION_RULE_MAP))
        if missing:
            errors.append(f'dimensions 缺少：{missing}')
        if extra:
            errors.append(f'dimensions 含未注册维度：{extra}')

        for dimension_name, expected_rule_id in DIMENSION_RULE_MAP.items():
            dimension = dimensions.get(dimension_name)
            if not isinstance(dimension, dict):
                if dimension_name in dimensions:
                    errors.append(f'dimensions.{dimension_name} 必须是对象')
                continue
            errors.extend(self._validate_dimension(dimension_name, expected_rule_id, dimension))

        return errors

    def _validate_dimension(self, dimension_name: str, expected_rule_id: str, dimension: Dict[str, Any]) -> List[str]:
        errors: List[str] = []

        if dimension.get('rule_id') != expected_rule_id:
            errors.append(f'dimensions.{dimension_name}.rule_id 必须是 {expected_rule_id}')

        evaluation = dimension.get('evaluation')
        if not isinstance(evaluation, dict):
            errors.append(f'dimensions.{dimension_name}.evaluation 必须是对象')
        else:
            if evaluation.get('order') != ['fail', 'risk', 'pass']:
                errors.append(f'dimensions.{dimension_name}.evaluation.order 必须是 [\"fail\", \"risk\", \"pass\"]')
            if evaluation.get('mode') != 'first_match':
                errors.append(f'dimensions.{dimension_name}.evaluation.mode 必须是 first_match')

        metrics = dimension.get('metrics')
        if not isinstance(metrics, list):
            errors.append(f'dimensions.{dimension_name}.metrics 必须是数组')
        else:
            metric_names = [metric.get('name') for metric in metrics if isinstance(metric, dict)]
            duplicates = sorted({name for name in metric_names if name and metric_names.count(name) > 1})
            if duplicates:
                errors.append(f'dimensions.{dimension_name}.metrics 存在重复 name：{duplicates}')
            for index, metric in enumerate(metrics):
                errors.extend(self._validate_metric(dimension_name, index, metric))

        outcomes = dimension.get('outcomes')
        if not isinstance(outcomes, list) or not outcomes:
            errors.append(f'dimensions.{dimension_name}.outcomes 必须是非空数组')
        else:
            errors.extend(self._validate_outcomes(dimension_name, expected_rule_id, outcomes))

        return errors

    def _validate_metric(self, dimension_name: str, index: int, metric: Any) -> List[str]:
        errors: List[str] = []
        prefix = f'dimensions.{dimension_name}.metrics[{index}]'

        if not isinstance(metric, dict):
            return [f'{prefix} 必须是对象']

        if not metric.get('name'):
            errors.append(f'{prefix}.name 不能为空')
        if not metric.get('function'):
            errors.append(f'{prefix}.function 不能为空')
        if not metric.get('selector'):
            errors.append(f'{prefix}.selector 不能为空')
        if 'where' in metric:
            errors.extend(self._validate_condition(metric.get('where'), f'{prefix}.where'))
        return errors

    def _validate_outcomes(self, dimension_name: str, expected_rule_id: str, outcomes: List[Any]) -> List[str]:
        errors: List[str] = []
        previous_rank = -1
        has_pass = False

        for index, outcome in enumerate(outcomes):
            prefix = f'dimensions.{dimension_name}.outcomes[{index}]'
            if not isinstance(outcome, dict):
                errors.append(f'{prefix} 必须是对象')
                continue

            status = outcome.get('status')
            risk_level = outcome.get('risk_level')
            trigger_rule = outcome.get('trigger_rule')

            if status not in STATUS_RANK:
                errors.append(f'{prefix}.status 无效：{status}')
                continue

            rank = STATUS_RANK[status]
            if rank < previous_rank:
                errors.append(f'{prefix}.status 顺序错误，必须先 fail，再 risk，最后 pass')
            previous_rank = rank

            if status == 'pass':
                has_pass = True
                if risk_level != 'none':
                    errors.append(f'{prefix} 为 pass 时 risk_level 必须是 none')
            elif status == 'risk' and risk_level not in {'low', 'medium', 'high'}:
                errors.append(f'{prefix} 为 risk 时 risk_level 必须为 low/medium/high')
            elif status == 'fail' and risk_level != 'high':
                errors.append(f'{prefix} 为 fail 时 risk_level 必须是 high')

            if trigger_rule != expected_rule_id:
                errors.append(f'{prefix}.trigger_rule 必须与 rule_id 一致，期望 {expected_rule_id}')

            errors.extend(self._validate_condition(outcome.get('when'), f'{prefix}.when'))
            errors.extend(self._validate_evidence_policy(outcome.get('evidence_policy'), f'{prefix}.evidence_policy'))

        if not has_pass:
            errors.append(f'dimensions.{dimension_name}.outcomes 必须至少有一个 pass 分支')
        return errors

    def _validate_evidence_policy(self, evidence_policy: Any, path: str) -> List[str]:
        errors: List[str] = []
        if not isinstance(evidence_policy, dict):
            return [f'{path} 必须是对象']

        mode = evidence_policy.get('mode')
        selector = evidence_policy.get('selector')
        min_items = evidence_policy.get('min_items')
        max_items = evidence_policy.get('max_items')

        if mode not in {'filter', 'none'}:
            errors.append(f'{path}.mode 必须是 filter 或 none')
        if not isinstance(selector, str) or not selector:
            errors.append(f'{path}.selector 不能为空')
        if not isinstance(min_items, int) or min_items < 0:
            errors.append(f'{path}.min_items 必须是 >= 0 的整数')
        if not isinstance(max_items, int) or max_items < 0:
            errors.append(f'{path}.max_items 必须是 >= 0 的整数')
        elif isinstance(min_items, int) and max_items < min_items:
            errors.append(f'{path}.max_items 不能小于 min_items')

        if mode == 'none':
            if min_items != 0 or max_items != 0:
                errors.append(f'{path} 在 mode = none 时，min_items 和 max_items 必须都为 0')
        elif 'where' in evidence_policy:
            errors.extend(self._validate_condition(evidence_policy.get('where'), f'{path}.where'))

        return errors

    def _validate_condition(self, condition: Any, path: str) -> List[str]:
        errors: List[str] = []
        if not isinstance(condition, dict):
            return [f'{path} 必须是对象']

        keys = set(condition)
        if keys == {'all'}:
            items = condition.get('all')
            if not isinstance(items, list) or not items:
                errors.append(f'{path}.all 必须是非空数组')
            else:
                for index, item in enumerate(items):
                    errors.extend(self._validate_condition(item, f'{path}.all[{index}]'))
            return errors

        if keys == {'any'}:
            items = condition.get('any')
            if not isinstance(items, list) or not items:
                errors.append(f'{path}.any 必须是非空数组')
            else:
                for index, item in enumerate(items):
                    errors.extend(self._validate_condition(item, f'{path}.any[{index}]'))
            return errors

        if keys == {'not'}:
            errors.extend(self._validate_condition(condition.get('not'), f'{path}.not'))
            return errors

        if 'left' not in condition or 'op' not in condition:
            return [f'{path} 必须是 all/any/not/comparison 之一']

        op = condition.get('op')
        if op not in COMPARISON_OPS:
            errors.append(f'{path}.op 无效：{op}')

        if op == 'between':
            if 'lower' not in condition or 'upper' not in condition:
                errors.append(f'{path} 在 op = between 时必须包含 lower 和 upper')
        elif op != 'exists' and 'right' not in condition:
            errors.append(f'{path} 在 op = {op} 时必须包含 right')

        return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='校验 BigPOI QC 规则 DSL')
    parser.add_argument(
        'dsl_file',
        nargs='?',
        default='./rules/decision_tables.json',
        help='要校验的 DSL 文件路径',
    )
    parser.add_argument(
        '--schema',
        default='./schema/decision_tables.schema.json',
        help='DSL Schema 文件路径',
    )
    parser.add_argument(
        '--output-format',
        choices=['text', 'json'],
        default='text',
        help='输出格式',
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    validator = DslValidator(args.dsl_file, args.schema)
    result = validator.validate()

    if args.output_format == 'json':
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"校验状态: {result['status']}")
        print(f"是否有效: {result['is_valid']}")
        if result['errors']:
            print('错误:')
            for error in result['errors']:
                print(f'  - {error}')
        if result['warnings']:
            print('警告:')
            for warning in result['warnings']:
                print(f'  - {warning}')

    return 0 if result['is_valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
