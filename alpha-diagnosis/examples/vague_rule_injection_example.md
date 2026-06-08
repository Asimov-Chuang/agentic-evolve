# vague_rule_injection 示例

在 workflow 的 `injection` 段开启 `vague_rule_injection: true` 即可。Discovery 仍产出带 fraction 的精确 rule 描述；inject 阶段会自动转成自然语言，不再出现 "accounts for more than 25% of actions" 这类阈值表述。

## 配置示例

```yaml
injection:
  mode: per_rule_variants
  include_rule_weights: false
  max_submissions: 8
  vague_rule_injection: true   # 开启模糊自然语言注入
```

完整 workflow 可参考 `workflows/sustaindc_rich_feedback_vague.yaml`。

## Prompt 对比

以下 8 条 rule 来自 SustainDC discovery 的典型输出（精确版）。开启 `vague_rule_injection` 后，inject prompt 中的 Factor 段落会变成右侧样式。

| Rule name | 精确描述（默认） | 模糊描述（vague_rule_injection: true） |
|-----------|------------------|----------------------------------------|
| defer_under_high_ci | On high carbon-intensity steps (agent_ls ci_current > 0.60), defer (0) accounts for more than 25% of actions. | When carbon intensity is high, deferring flexible workloads tends to be important for higher scores. |
| execute_under_queue_pressure | On load-shifting queue fill ratio high steps (agent_ls queue_fill > 0.40), execute (2) accounts for more than 30% of actions. | When the load-shifting queue is crowded, executing queued workloads tends to be important for higher scores. |
| more_cooling_when_hot | On hot outdoor-temp steps (agent_dc outdoor_temp > 0.65), more-cool (0) accounts for more than 20% of actions. | When outdoor temperature is hot, increasing cooling effort tends to be important for higher scores. |
| idle_future_ci_per_scenario | In every scenario, when battery future carbon intensity mean > 0.62, idle (2) accounts for more than 10% of those timesteps. | When expected future carbon intensity is high, keeping the battery idle tends to be important for higher scores. |
| pre_cool_when_future_hot | On warm outdoor-temp steps (agent_dc outdoor_temp > 0.55), more-cool (0) accounts for more than 15% of actions. | When outdoor temperature is warm, increasing cooling effort tends to be important for higher scores. |
| discharge_high_ci_high_bar | On high carbon-intensity steps (agent_bat ci_current > 0.55), discharge (1) accounts for more than 20% of actions. | When carbon intensity is high, using battery discharge tends to be important for higher scores. |
| discharge_high_soc | On battery SOC high steps (agent_bat soc > 0.60), discharge (1) accounts for more than 15% of actions. | When battery state of charge is high, using battery discharge tends to be important for higher scores. |
| overall_defer_fraction | Overall, defer (0) accounts for more than 15% of agent_ls actions. | In general operation, deferring flexible workloads tends to be important for higher scores. |

## Inject prompt 片段（vague 模式）

```markdown
---

## Diagnostic factors for algorithm improvement

Through analysis of high-performing programs, we identified the following 8 behavioral patterns that matter for improving performance. Use them as qualitative design guidance when proposing new algorithms.

**Important:** Treat each pattern below as an independent design principle. Do NOT assume any relative importance or weight among them — focus only on the behavioral intent described.

### Factor 1: defer_under_high_ci
When carbon intensity is high, deferring flexible workloads tends to be important for higher scores.

### Factor 2: execute_under_queue_pressure
When the load-shifting queue is crowded, executing queued workloads tends to be important for higher scores.

### Factor 3: more_cooling_when_hot
When outdoor temperature is hot, increasing cooling effort tends to be important for higher scores.

...

---

## Your task

Based on the current best program (attempt_0091 / best_program.py) as the starting baseline, **design and submit exactly 8 new algorithm variants** — one per factor above:

1. **Algorithm 1** — primarily targets Factor 1 (defer_under_high_ci)
2. **Algorithm 2** — primarily targets Factor 2 (execute_under_queue_pressure)
...
```

与默认模式相比：Factor 段落不再包含 action id、obs 阈值和 fraction 百分比，只保留「在什么情况下、什么行为倾向更重要」的定性指导。
