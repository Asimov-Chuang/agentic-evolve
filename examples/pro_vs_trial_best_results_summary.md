# 前 100 次 Submission：Pro vs Trial 最佳结果与 Agent Trace 分析

本文只分析每个 run 的前 100 次 `submit` 事件；第 101 次及之后的 submission 不参与最佳结果、指标对比或原因分析。`backfill` / seed 只作为初始基线记录，最佳 candidate 必须来自前 100 次 submit 范围内。

## 口径说明

- `pro`：使用配置中 `mode: pro` 的顶层输出目录，即 `*_pro*` 系列。
- `trial`：优先使用显式 `*_trial*` 目录；SustainDC 没有 `trial*` 顶层目录，因此采用非 pro 且 prompt 标注为 resumed evolution workspace 的 `sustaindc_X` 作为 trial 对照。
- 分数口径：逐行读取顶层 `score_trajectory.jsonl`，只保留前 100 个 `event == "submit"`，取其中最高 `score` / `best_so_far` 对应的 attempt。
- 三个任务均为分数越高越好。

## 总览

| 任务 | Pro 前 100 最佳 | Trial 前 100 最佳 | 胜出方 | 差值 | 结论 |
| --- | ---: | ---: | --- | ---: | --- |
| Adaptive Temporal Smooth Control | 0.8420968883 (`optics_temporal_smooth_pro3`, submit #31, attempt_0031) | 0.8424077042 (`optics_temporal_smooth_trial1`, submit #99, attempt_0099) | Trial | +0.0003108159 | 两者都接近物理/评分平台，trial 靠 rate-limit delta 与 forward prediction 微调略胜。 |
| SustainDC | 31.7780 (`sustaindc_pro`, submit #100, attempt_0100) | 21.5783 (`sustaindc_X`, submit #98, attempt_0086) | Pro | +10.1997 | 前 100 内 pro 已完成 analyzer 修复、冷却突破和 LS/电池规则整合；trial 的后期改进不计入后差距很大。 |
| PID Tuning | 0.1638163827 (`pid_tuning_pro`, submit #25, attempt_0025) | 0.1634004983 (`pid_tuning_trial3`, submit #50, attempt_0057) | Pro | +0.0004158843 | 两者都找到 cascade-balanced PID 区域；pro 更早识别场景瓶颈与 gain saturation，微幅胜出。 |

## 任务一：Adaptive Temporal Smooth Control

### 前 100 最佳结果

| 模式 | 输出目录 | submit 序号 | 最佳 attempt | 分数 | mean_rms | mean_slew | mean_strehl | raw_cost |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| Pro | `outputs/optics_temporal_smooth_pro3` | 31 | attempt_0031 | 0.8420968883 | 1.692316 | 0.043919 | 0.162212 | 1.920695 |
| Trial | `outputs/optics_temporal_smooth_trial1` | 99 | attempt_0099 | 0.8424077042 | 1.691645 | 0.042465 | 0.162309 | 1.912461 |

Trial 在前 100 次 submission 内比 pro 高约 0.00031。这个差距很小，但方向稳定：trial 的 `mean_rms`、`mean_slew`、`mean_strehl` 都略好。

### Agent trace 解释

Pro trace 很早识别出核心瓶颈：`smooth_reconstructor + prev_blend` 是基础，soft-clip / lowpass 能把 clipping 降到 0%，并把 slew 压到评分 good anchor 附近。analyzer 反复提示 `u_mean_slew` 已经满分，剩余弱项是 RMS 与 Strehl；尝试 EMA-only、adaptive gain、lead compensation 等结构后，分数基本卡在 0.842 左右。

Trial trace 在前 100 内更集中地做了局部参数搜索：保留 hard rate limit `±0.055`，在 delta 空间使用 `delay_prediction_gain` 放大有效小步修正，并同时细调 raw blend 与 prev_blend。最佳 attempt_0099 已经接近后续 attempt_0124 的最终水平，说明 trial 的主要收益在前 100 内已经实现。

结论：ATSC 是“接近物理上限后的精细参数微调”任务，trial 在前 100 内略优；pro 的结构化 analyzer 帮助确认平台，但没有把平台附近的微调做到 trial 那么极致。

## 任务二：SustainDC

### 前 100 最佳结果

| 模式 | 输出目录 | submit 序号 | 最佳 attempt | 分数 | Carbon kg | Water L | Dropped / Overdue |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| Pro | `outputs/sustaindc_pro` | 100 | attempt_0100 | 31.7780 | 75,208.37 | 999,298.35 | 0 / 0 |
| Trial | `outputs/sustaindc_X` | 98 | attempt_0086 | 21.5783 | 83,462.61 | 974,779.15 | 0 / 0 |

Pro 在前 100 次 submission 内领先 10.1997 分。Pro 的 water 用量更高，但 carbon 明显更低；两者都没有 dropped / overdue tasks。由于 water usage 仍未低于 noop，前 100 内的胜负主要由 carbon reduction 和安全约束下的调度效率决定。

Pro attempt_0100 场景分数：

- az_july=31.75
- ca_april=33.90
- ny_january=30.49
- tx_august=30.97

Trial attempt_0086 场景分数：

- az_july=6.91
- ca_april=29.80
- ny_january=20.60
- tx_august=29.00

差距最大的是 `az_july`：pro 已经把该场景推到 31.75，而 trial 前 100 内仍只有 6.91。

### Agent trace 解释

Pro 在前 100 内完成了几次关键跃迁：

- 修复 analyzer 对 raw artifact 的理解：trace 记录了 key 实际为 `agent_ls`、`agent_dc`、`agent_bat`，并补齐 `common` 字段中的 SOC、CI、queue、temperature、power/water 信息。这个修复使反馈从粗略分数变成 per-scenario 轨迹诊断。
- 负载迁移与电池早期规则：基于 CI percentile、future mean、queue age、SOC 等信号，形成高 CI defer、低 CI execute、低 CI 充电、高 CI 放电的策略。前 100 内 pro 的 `ls_keep_fraction=0.000`，说明 agent 已经把 keep fallback 改成更主动的 CI 条件决策。
- 冷却突破：trace 明确发现 `LESS_COOL` 和 `KEEP` 在多个场景中会增加 energy/carbon，反直觉地验证 100% `MORE_COOL` 最优。attempt_0100 的 trajectory 中 `dc_more_cooling_fraction=1.000`、`dc_less_cooling_fraction=0.000`。
- 前 100 内已经开始处理 az_july 的特殊性：az_july CI 范围高，常规低 CI 充电很难触发；pro 通过 LS 和少量 battery activation 把该场景拉上来。

Trial `sustaindc_X` 在前 100 内还没有完成后期那些关键修正。attempt_0086 的 feedback 仍提示 average battery SOC 很低、battery dispatch 可能过激，且 worst scenarios 是 `az_july` 和 `ny_january`。虽然 ca_april / tx_august 已有不错表现，但 az_july 仍严重拖后腿。

结论：在只看前 100 次时，SustainDC 更能体现 pro 模式的优势。pro 的 analyzer evolution 很早把复杂多 agent 轨迹转化为可执行假设，并在 100 次内完成冷却策略与 LS 策略突破；trial 的许多后期提升被截断后，尚未解决 az_july 和低 SOC 问题。

## 任务三：PID Tuning

### 前 100 最佳结果

| 模式 | 输出目录 | submit 序号 | 最佳 attempt | 分数 | vertical_hover ITAE | lateral_move ITAE | combined_wind ITAE | multi_waypoint ITAE |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| Pro | `outputs/pid_tuning_pro` | 25 | attempt_0025 | 0.1638163827 | 1.581865 | 3.756428 | 8.959301 | 26.082676 |
| Trial | `outputs/pid_tuning_trial3` | 50 | attempt_0057 | 0.1634004983 | 1.586011 | 3.756602 | 9.017156 | 26.110517 |

Pro 在前 100 内高 0.000416。两者已经非常接近，但 pro 在 `combined_wind` 与 `multi_waypoint` 上略好；这些是更难的场景，因此对综合分更关键。

### Agent trace 解释

两个模式都在前 100 内发现了 cascade-balanced PID 的核心规律：

- 初始 bang-bang 或横向控制不足会导致低分。
- 需要提高 inner pitch loop authority，同时避免外环 `Kp_x` 过强。
- `Ki_z`、`Ki_x` 基本保持 0，积分项通常伤害跨场景鲁棒性。
- `N_x`、`N_theta` 接近上界，较少 derivative filtering 有利于快速响应。
- `multi_waypoint` 和 `combined_wind` 是主要瓶颈。

Pro attempt_0025 的 gains 更激进地利用 altitude loop 和 derivative filters：`Kp_z=29.82` 接近上界，`N_x=99.70`、`N_theta=99.99` 接近上界。Analyzer feedback 也明确指出 gain utilization、ITAE spread、场景约束，帮助搜索快速聚焦到高 authority 但仍可行的区域。

Trial attempt_0057 也已经接近同一区域，但 `Kp_z=25.03`、`N_x=88.55`、`N_theta=88.33` 相对保守，combined_wind 与 multi_waypoint 略差。它的 trace 展示了随机搜索、manual candidates、bounds 修正等有效探索，但在前 100 内还没有超过 pro。

结论：PID 在前 100 内 pro 小幅胜出。核心不是找到完全不同的控制结构，而是 pro 更早识别并利用瓶颈场景和 gain bounds，使搜索在有限 submission 内更高效。

## 前 100 次口径下的综合结论

- ATSC：trial 略优，说明当反馈直接、目标接近硬物理平台时，前 100 内的局部参数搜索可以胜过 analyzer-driven 的系统诊断。
- SustainDC：pro 大幅领先，说明多 agent、多场景、raw trace 复杂的任务中，前 100 内能否快速构建有效 analyzer 非常关键。
- PID：pro 微幅领先，说明高维连续优化中，analyzer 对场景瓶颈、约束饱和和 gain utilization 的总结能提高早期搜索效率。

整体看，只聚焦前 100 次 submission 后，pro 的“早期学习效率”优势更明显，尤其在 SustainDC 上；trial 的后期追赶和长预算收益不再计入。

## 主要证据文件

- `adaptive_temporal_smooth_control/outputs/optics_temporal_smooth_pro3/score_trajectory.jsonl`
- `adaptive_temporal_smooth_control/outputs/optics_temporal_smooth_trial1/score_trajectory.jsonl`
- `sustaindc/outputs/sustaindc_pro/score_trajectory.jsonl`
- `sustaindc/outputs/sustaindc_X/score_trajectory.jsonl`
- `pid_tuning/outputs/pid_tuning_pro/score_trajectory.jsonl`
- `pid_tuning/outputs/pid_tuning_trial3/score_trajectory.jsonl`
- 各前 100 最佳 attempt 的 `archive/attempt_*/result.json`、`raw-artifact.json`、`code.py`
- 各 run 的 `agent_stdout.log`
