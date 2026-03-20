# 伪代码参考

本文件为 v2.0.0 的简化伪代码说明，权威规则仍然是 `decision_tables.json`。

```text
1. 校验输入完整性
   if task_id / name / coordinates / address / administrative / category / evidence_data 缺失:
       输出 impacted dimensions = fail
       qc_status = unqualified
       qc_score = 0
       stop

2. 依次判定六个核心维度
   for dim in [existence, name, location, address, administrative, category]:
       先检查 fail 条件
       再检查 risk 条件
       否则 pass

3. 推导 qc_manual_review_required
   qc_manual_review_required = any(core_dimension.status != pass)

4. 推导 upstream_manual_review_required
   先看 downgrade_info.is_downgraded
   再看 overall.action == manual_review
   再看 overall.status in [manual_review, downgraded]

5. 判定 downgrade_consistency
   if qc_manual_review_required == upstream_manual_review_required:
       pass
   else:
       fail

6. 根据 scoring_policy.json 计算 qc_score

7. 聚合 qc_status / risk_dims / statistics_flags
```
