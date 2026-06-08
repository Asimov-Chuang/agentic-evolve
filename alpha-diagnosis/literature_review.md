# alpha-diagnosis 相关工作综述草稿

本文面向 `agentic-evolve/alpha-diagnosis` 的 related work 写作。`alpha-diagnosis` 的关键机制可以概括为：当主进化任务陷入停滞时，从已生成尝试的轨迹与分数中自动发现可解释的诊断规则，再把这些规则注入回主任务提示中，引导后续代码/策略进化继续搜索。因此它位于多条研究线的交叉处：反馈驱动的 agent 自改进、verifier/evaluator/rubric 学习、LLM 驱动的算法发现与进化、自动软件工程 agent，以及提示/工作流/算子设计的自动优化。

## 总体判断：是否已有雷同工作

| 结论 | 说明 |
| --- | --- |
| 未发现完全雷同工作 | 目前代表作大多优化“候选程序/提示/奖励函数/agent 行为”本身，或训练/使用 judge、verifier、rubric；较少有工作把失败轨迹转化为一组显式、可评分、可注入的诊断规则，并用这些规则重启/继续另一个进化式 coding loop。 |
| 最接近方向 | GEPA、Reflexion、Eureka、FunSearch/AlphaEvolve、TextGrad/ProTeGi、Dynamic Rubrics/Rubric-ARM、EvoLM、EvoRubric、Agentic Rubrics。它们都利用执行反馈、自然语言诊断、rubric 或 evaluator 信号指导下一轮搜索。 |
| 主要差异点 | `alpha-diagnosis` 不是直接把反馈写成一次性 reflection，也不是训练一个通用 verifier；它把历史 trajectory archive 作为数据源，另起一个 rule discovery 任务来进化诊断规则，再把发现的规则作为可复用的中间知识注入主进化任务。 |
| 潜在 novelty 表述 | “diagnostic rule discovery as a meta-evolution loop for stalled LLM code evolution”：规则是从主任务经验中自动挖掘出来的、可解释的、任务特定的反馈压缩层。 |
| 2026 年后的 novelty 压力 | 2026 年 rubric/evaluator co-evolution 工作明显增多，尤其是 EvoLM、EvoRubric、Rubric-ARM、CDRRM 和 Agentic Rubrics。写作时需要避免把 novelty 放在“自动生成 rubric/规则”本身，而应放在“从主进化轨迹中发现诊断规则，并作为停滞恢复机制回注到算法/代码进化 loop”。 |

## 1. Feedback、Reflection 与 Verbal Reinforcement

| 工作 | 年份 | 核心思想 | 与 `alpha-diagnosis` 的关系 | 差异/可借鉴点 | 相似度 |
| --- | --- | --- | --- | --- | --- |
| Self-Refine: Iterative Refinement with Self-Feedback ([arXiv](https://arxiv.org/abs/2303.17651)) | 2023 | LLM 对自己的输出生成反馈，再根据反馈迭代改写，无需训练。 | 都把自然语言反馈作为改进信号。 | Self-Refine 面向单个输出的局部迭代；`alpha-diagnosis` 从多次尝试和分数中归纳规则，并注入后续进化。 | 中 |
| Reflexion: Language Agents with Verbal Reinforcement Learning ([arXiv](https://arxiv.org/abs/2303.11366), [OpenReview](https://openreview.net/forum?id=vAElhFcKW6)) | 2023 | 将环境标量/二值反馈转成 verbal reflection，存入 episodic memory，供下一次 agent 尝试使用。 | 非常接近“从失败中总结经验再重试”的思想。 | Reflexion 通常生成自由文本 reflection；`alpha-diagnosis` 进化结构化诊断规则，并以规则发现任务筛选规则质量。 | 高 |
| ReAct: Synergizing Reasoning and Acting in Language Models ([arXiv](https://arxiv.org/abs/2210.03629)) | 2022 | 交替生成 reasoning trace 与 actions，让 LLM 能与工具/环境交互。 | 为 trajectory-based agent 提供基础范式。 | ReAct 不做跨尝试规则学习；可作为主任务 agent 的行为框架背景引用。 | 低 |
| Constitutional AI / RLAIF ([arXiv](https://arxiv.org/abs/2212.08073)) | 2022 | 用一组宪法原则让模型自我批判与修订，并用 AI feedback 训练偏好模型。 | 都将显式规则/原则用于反馈和改进。 | CAI 的原则通常由人写或固定；`alpha-diagnosis` 自动从任务轨迹中发现任务特定规则。 | 中 |
| RLAIF vs. RLHF ([arXiv](https://arxiv.org/abs/2309.00267)) | 2023 | 系统比较 AI feedback 与 human feedback，并研究直接用 LLM 提供 reward。 | 支持“AI feedback 可替代部分人工反馈”的大背景。 | 主要是训练策略模型/奖励模型；不是发现诊断规则。 | 低 |
| Self-Rewarding Language Models ([PMLR](https://proceedings.mlr.press/v235/yuan24d.html), [arXiv](https://arxiv.org/abs/2401.10020)) | 2024 | 模型既生成回答又用 LLM-as-a-Judge 给自己打分，迭代构造 DPO 数据。 | 与“自生成评价信号”相关。 | 它优化模型权重与 judge 能力；`alpha-diagnosis` 优化外部规则和 coding loop，不训练模型。 | 中 |
| Meta-Rewarding Language Models ([arXiv](https://arxiv.org/abs/2407.19594), [ACL Anthology](https://aclanthology.org/2025.emnlp-main.583/)) | 2024/2025 | 增加 meta-judge 来评价 judge 的判断，从而提升自奖励质量。 | 与“评价器的评价器/二阶反馈”相关。 | `alpha-diagnosis` 的 discovery evaluator 可被表述成对规则质量的 meta-evaluation，但目前不是训练 judge。 | 中 |
| Multi-Agent Verification (MAV) ([OpenReview](https://openreview.net/forum?id=LriQ3NY9uL)) | 2025/2026 | 使用多个 aspect verifiers 扩展 test-time verification compute。 | 与多维诊断规则/多个 verifier 组合相关。 | MAV 聚焦 test-time 选择答案；`alpha-diagnosis` 聚焦从历史轨迹学习可注入规则。 | 中 |

## 2. Verifier、Critic、Evaluator 与 LLM-as-a-Judge

| 工作 | 年份 | 核心思想 | 与 `alpha-diagnosis` 的关系 | 差异/可借鉴点 | 相似度 |
| --- | --- | --- | --- | --- | --- |
| G-Eval ([arXiv](https://arxiv.org/abs/2303.16634)) | 2023 | 用 GPT-4 与 chain-of-thought 根据自定义 criteria 评估自然语言生成。 | 体现“自然语言 criteria + LLM judge”的早期主流形式。 | criteria 通常人工定义；`alpha-diagnosis` 自动发现 criteria/rules。 | 中 |
| Prometheus / Prometheus 2 ([arXiv](https://arxiv.org/abs/2405.01535)) | 2023/2024 | 训练开源 evaluator LM，支持 direct assessment 与 pairwise ranking，并使用细粒度评分标准。 | 与 evaluator specialization 和 rubric-based judging 相关。 | Prometheus 学习通用 evaluator；`alpha-diagnosis` 发现任务特定诊断规则并回注到生成过程。 | 中 |
| AUTO-J ([ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/747dc7c6566c74eb9a663bcd8d057c78-Abstract-Conference.html)) | 2024 | 训练可生成 critique 的 13B judge，覆盖多种评估协议。 | 与自然语言 critique 和 judge 训练相关。 | 需要训练 evaluator；`alpha-diagnosis` 使用现有 agent/evaluator 进行规则发现。 | 低-中 |
| CriticGPT / LLM Critics Help Catch LLM Bugs ([OpenAI](https://openai.com/index/finding-gpt4s-mistakes-with-gpt-4/), [arXiv](https://arxiv.org/abs/2407.00215)) | 2024 | 训练 critic 模型帮助人类发现 LLM 生成代码中的 bug。 | 与 coding feedback/verifier 很相关，尤其是代码错误诊断。 | CriticGPT 是监督/偏好训练的 critic；`alpha-diagnosis` 是从进化轨迹中发现规则，不训练专门 critic。 | 中 |
| V-STaR: Training Verifiers for Self-Taught Reasoners ([arXiv](https://arxiv.org/abs/2402.06457)) | 2024 | 用自生成的正确/错误解构造偏好对，通过 DPO 训练 verifier，再用 verifier 排序候选。 | 与“从成功/失败样本训练或改进 verifier”相关。 | V-STaR 学 verifier 参数；`alpha-diagnosis` 进化可解释规则，并把规则用于提示注入。 | 中 |
| DeepSeek-R1 / RL with Verifiable Rewards ([arXiv](https://arxiv.org/abs/2501.12948)) | 2025 | 使用规则化、可验证 reward 进行大规模 RL，强调避免神经 reward hacking。 | 支持“规则化 verifier/reward 比黑盒 reward 更稳”的论点。 | R1 依赖人工设计的 accuracy/format reward；`alpha-diagnosis` 尝试自动发现任务诊断规则。 | 中 |
| Agentic Rubrics as Contextual Verifiers for SWE Agents ([arXiv](https://arxiv.org/abs/2601.04171)) | 2026 | 专家 agent 先浏览代码库并生成结构化 `rubrics.yaml`，再用该 rubric 对候选 patch 进行免执行评分。 | 与“agent 自动生成结构化、上下文相关 verifier/rubric”非常接近，且同属 SWE/coding agent 场景。 | Agentic Rubrics 主要用于 patch ranking / test-time scaling；`alpha-diagnosis` 从历史进化轨迹中发现诊断规则，并把规则用于继续生成更好的候选，而不只是验证候选。 | 高 |
| LLM-as-a-Judge Survey ([arXiv](https://arxiv.org/abs/2411.15594)) | 2024 | 系统综述 judge 的使用、偏差、可靠性和训练方法。 | 可作为 evaluator 背景综述引用。 | 不是具体方法，但适合 related work 开头。 | 低 |

## 3. Rubric Learning、Dynamic Rubric 与 Criteria Discovery

| 工作 | 年份 | 核心思想 | 与 `alpha-diagnosis` 的关系 | 差异/可借鉴点 | 相似度 |
| --- | --- | --- | --- | --- | --- |
| FLASK: Fine-grained Language Model Evaluation ([arXiv](https://arxiv.org/abs/2307.10928)) | 2023 | 将 LLM 输出质量拆成多个细粒度 skill/criteria 评分。 | 与多维评价标准和诊断维度相关。 | FLASK 的 criteria 是 benchmark 设计；`alpha-diagnosis` 的 rules 从任务轨迹中发现。 | 中 |
| Generating and Refining Dynamic Evaluation Rubrics for LLM-as-a-Judge ([arXiv](https://arxiv.org/abs/2605.30568)) | 2026 | 自动生成 dataset/instance-specific rubric，并用 meta-judge preference learning 微调 rubric generator。 | 非常接近“自动生成/优化评价标准”。 | 它优化 judge 的 rubric；`alpha-diagnosis` 优化用于引导主任务 evolution 的诊断规则。可重点对比。 | 高 |
| Rubric-Based Reward Modeling / Rubric-RM | 2025/2026 | 用显式 rubric 指导 reward model 或 pairwise preference prediction。 | 与“结构化自然语言规则作为 reward/evaluation 中间层”相关。 | 主要服务 reward modeling；`alpha-diagnosis` 的规则同时承担诊断和生成引导。 | 中 |
| Rubric-ARM | 2026 | 将 rubric generator 与 judge 作为两个组件交替 RL 优化，使二者共同进化。 | 与“rubric 与 evaluator co-evolve”高度相关。 | Rubric-ARM 是模型训练框架；`alpha-diagnosis` 是无需训练的任务级规则发现与注入框架。 | 高 |
| EvoLM: Self-Evolving Language Models through Co-Evolved Discriminative Rubrics ([arXiv](https://arxiv.org/abs/2605.03871)) | 2026 | 在同一个模型中交替训练 rubric generator 与 policy，用 temporal contrast 自动构造偏好信号；rubric 被优化成帮助 frozen judge 区分好坏输出的 discriminative criteria。 | 与“规则/rubric 和生成器共同进化”高度相关，是 2026 年最需要正面对比的工作之一。 | EvoLM 训练模型参数，目标是自监督 post-training；`alpha-diagnosis` 不训练模型，而是在外部进化系统中把 archive 蒸馏成可注入诊断规则。 | 高 |
| EvoRubric: Self-Evolving Rubric-Driven RL for Open-Ended Generation ([arXiv](https://arxiv.org/abs/2605.29847)) | 2026 | 单一 policy 在 Reasoner 与 Rubric Generator 两个角色间切换，动态生成并验证 rubric，形成 rubric memory pool，用于开放式生成 RL。 | 与“rubric memory / self-evolving criteria / multi-level verification”很接近。 | EvoRubric 的规则是训练 reward 的组成部分；`alpha-diagnosis` 的规则来自已发生的主任务进化轨迹，并作为停滞恢复提示注入。 | 高 |
| CDRRM: Contrast-Driven Rubric Generation for Reliable and Interpretable Reward Modeling ([arXiv](https://arxiv.org/abs/2603.08035)) | 2026 | 对 preference pairs 做多维 contrastive profiling，提取导致偏好差异的因果因素，再合成为紧凑 rubric 以指导 reward model。 | 与“从好坏样本对中提取判别性规则”非常相关。 | CDRRM 面向 preference/reward modeling；`alpha-diagnosis` 面向 trajectory-to-rule discovery，并把规则用于搜索干预。 | 高 |
| Configurable Preference Tuning with Rubric-Guided Synthetic Data ([arXiv](https://arxiv.org/abs/2506.11702)) | 2025 | 用 rubric 和目标分数生成合成偏好数据，让模型按细粒度风格/目标可控。 | 与 rubric-to-instruction、rubric-guided generation 相关。 | 它把 rubric 用于训练偏好模型；`alpha-diagnosis` 把 rule 注入 agent prompt。 | 中 |
| OpenRubrics / Rubric datasets | 2025/2026 | 构建带 rubric 的偏好数据集，训练 rubric generator 与 reward model。 | 可作为 rubric learning 数据资源背景。 | 偏数据集与模型训练；不是进化式发现。 | 低 |

## 4. Prompt、Textual Gradient 与 Compound AI System Optimization

| 工作 | 年份 | 核心思想 | 与 `alpha-diagnosis` 的关系 | 差异/可借鉴点 | 相似度 |
| --- | --- | --- | --- | --- | --- |
| OPRO: Large Language Models as Optimizers ([arXiv](https://arxiv.org/abs/2309.03409)) | 2023 | 将历史候选 prompt 与分数放入 meta-prompt，让 LLM 生成更好的 prompt。 | 与“利用优化轨迹和分数指导下一轮候选生成”相近。 | OPRO 直接生成新 prompt；`alpha-diagnosis` 先发现规则，再由规则引导主任务。 | 高 |
| ProTeGi: Prompt Optimization with Textual Gradients ([ACL](https://aclanthology.org/2023.emnlp-main.494/)) | 2023 | LLM 生成自然语言“梯度”指出 prompt 缺陷，再编辑 prompt，并用 beam search 选择。 | 与“自然语言诊断作为优化方向”相近。 | ProTeGi 优化 prompt；`alpha-diagnosis` 优化任务规则/feedback abstraction。 | 高 |
| DSPy / MIPROv2 ([DSPy](https://dspy.ai/)) | 2023/2024 | 将 LM pipeline 写成模块化程序，并自动搜索 instruction 和 demos。 | 与 compound AI pipeline 自动优化相关。 | DSPy 更像编译器/optimizer；`alpha-diagnosis` 是进化停滞时的诊断-注入 loop。 | 中 |
| TextGrad ([arXiv](https://arxiv.org/abs/2406.07496), [Stanford HAI](https://hai.stanford.edu/news/textgrad-autograd-text)) | 2024 | 用 LLM 反馈模拟 autograd，在文本变量/提示/输出上反向传播自然语言反馈。 | 与“自然语言反馈可作为梯度”高度相关。 | TextGrad 优化任意文本变量；`alpha-diagnosis` 的文本变量是可解释规则集，并从 archive 中挖掘。 | 高 |
| GEPA: Reflective Prompt Evolution ([OpenReview](https://openreview.net/forum?id=RQm2KQTM5r), [GitHub](https://github.com/gepa-ai/gepa)) | 2025/2026 | 用完整执行轨迹、自然语言 reflection 与 Pareto 选择进化 prompt/代码/agent 配置。 | 最接近之一：都用执行轨迹中的 actionable side information 指导进化。 | GEPA 直接反思并变异候选文本；`alpha-diagnosis` 将反思显式外包为 rule discovery 子任务，生成可注入规则。 | 很高 |
| AFlow / Automated Agentic Workflow Generation | 2024/2025 | 自动搜索 LLM agent 工作流/模块组合，评估后迭代改进。 | 与 agent workflow discovery 相关。 | 多数工作搜索 workflow topology；`alpha-diagnosis` 搜索诊断规则并插入既有工作流。 | 中 |
| SCORE: Self-Evolving Deep Research via Joint Generation and Evaluation ([arXiv](https://arxiv.org/abs/2606.04507)) | 2026 | 针对 deep research 这类不可验证任务，让 solver 与 evaluator 共享参数并交替优化，同时用 meta-harness 控制评价环境。 | 与“生成器和评价器共同演化，避免 static evaluator 饱和”相关。 | SCORE 训练 shared-parameter research agent；`alpha-diagnosis` 是外部 workflow 层面的诊断规则发现，不进行参数训练。 | 中-高 |

## 5. LLM 驱动的算法 Discovery 与进化

| 工作 | 年份 | 核心思想 | 与 `alpha-diagnosis` 的关系 | 差异/可借鉴点 | 相似度 |
| --- | --- | --- | --- | --- | --- |
| FunSearch ([Nature](https://www.nature.com/articles/s41586-023-06924-6)) | 2023 | 冻结 LLM 与自动 evaluator 配对，在函数空间中进化代码，发现数学/算法新结果。 | 与 `agentic-evolve` 主线高度相关：LLM 生成候选，evaluator 选择，archive 驱动进化。 | FunSearch 主要进化目标函数/程序；`alpha-diagnosis` 进化诊断规则以帮助另一个进化过程。 | 高 |
| AlphaEvolve ([arXiv](https://arxiv.org/abs/2506.13131), [DeepMind](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)) | 2025 | 使用 LLM ensemble、自动 evaluator 和程序数据库，进化复杂算法/代码库。 | 与主系统“coding agent for algorithmic discovery”背景强相关。 | AlphaEvolve 关注候选算法本身；`alpha-diagnosis` 可定位为提升这类进化 loop 的 meta-diagnostic layer。 | 高 |
| Eureka ([OpenReview](https://openreview.net/forum?id=7RMTrQGrXS), [Project](https://eureka-research.github.io/)) | 2023/2024 | 用 LLM 生成并进化 reward code，通过 RL 训练机器人任务。 | 与“自动设计评价/奖励函数”非常相关。 | Eureka 发现 reward functions；`alpha-diagnosis` 发现诊断 rules，用于指导候选生成而非直接作为 reward。 | 高 |
| Voyager ([arXiv](https://arxiv.org/abs/2305.16291), [Project](https://voyager.minedojo.org/)) | 2023 | Minecraft lifelong agent，自动 curriculum、skill library、execution feedback/self-verification 改进代码技能。 | 与“轨迹反馈 + 可执行 skill/rule 库”相关。 | Voyager 累积可执行 skills；`alpha-diagnosis` 累积/注入诊断规则。 | 中 |
| Language Model Crossover (LMX) ([arXiv](https://arxiv.org/abs/2302.12170)) | 2023 | 将多个文本化 genotype 放进 prompt，让 LLM 通过 few-shot pattern completion 生成 offspring，可用于代码、公式、prompt 等文本基因。 | 是“LLM 作为 crossover/variation operator”的早期代表。 | LMX 关注通用 variation operator；`alpha-diagnosis` 不是直接替代 mutation/crossover，而是发现规则来指导后续生成。 | 中 |
| Large Language Models as Evolutionary Optimizers / LMEA ([arXiv](https://arxiv.org/abs/2310.19046)) | 2023/2024 | 在每代中让 LLM 选择父代、执行 crossover 和 mutation，并用温度自适应平衡探索/利用。 | 与“LLM 作为 selection+crossover+mutation 算子 agent”非常相关。 | LMEA 用 LLM 直接操作候选解；`alpha-diagnosis` 可以作为这种 evolution loop 的诊断与恢复层。 | 高 |
| LLaMEA ([arXiv](https://arxiv.org/abs/2405.20132)) | 2024 | LLM 作为进化算法，自动生成/变异/选择 metaheuristic optimizer。 | 与“LLM 设计优化算法/算子”相关。 | LLaMEA 直接生成优化算法类；`alpha-diagnosis` 生成任务诊断规则，服务主进化。 | 中-高 |
| LLaMEA-HPO ([arXiv](https://arxiv.org/abs/2410.16309)) | 2024 | 将 HPO 放入 LLaMEA loop，让 LLM 专注结构创新、HPO 调参数。 | 与“把不同优化器分工嵌入进化 loop”相关。 | 可借鉴 modular decomposition：规则发现负责结构性知识，主 agent 负责代码候选。 | 中 |
| LLaMEA-SAGE ([arXiv](https://arxiv.org/abs/2601.21511)) | 2026 | 从已评估算法代码中提取 AST/复杂度等结构特征，训练 surrogate 并用 explainable AI 找出影响性能的结构属性，再转成自然语言指导 LLM mutation。 | 与 `alpha-diagnosis` 很接近：都从 archive 中提取可解释信号，再转成自然语言指导后续搜索。 | SAGE 的诊断对象是算法代码结构特征；`alpha-diagnosis` 的诊断对象是完整尝试轨迹和任务表现规则。 | 高 |
| EoH: Evolution of Heuristics ([arXiv](https://arxiv.org/abs/2401.02051)) | 2024 | 将启发式同时表示为自然语言 thought 和可执行 code，使用多种 prompt strategy 共同进化 thought/code。 | 与“LLM 作为算法设计 agent”高度相关，尤其是自然语言 idea 与代码共同演化。 | EoH 的 thought 是候选启发式本体的一部分；`alpha-diagnosis` 的 rule 是关于候选成功/失败的诊断知识。 | 高 |
| ReEvo: LLMs as Hyper-Heuristics with Reflective Evolution ([arXiv](https://arxiv.org/abs/2402.01145), [NeurIPS](https://papers.nips.cc/paper_files/paper/2024/hash/4ced59d480e07d290b6f29fc8798f195-Abstract-Conference.html)) | 2024 | 让 LLM 作为 hyper-heuristic generator 和 reflector；通过短期 pairwise reflection 与长期 reflection 给 heuristic search 提供 verbal gradients。 | 与“比较好坏候选后生成反思/诊断信号”非常接近。 | ReEvo 的 reflection 直接服务 heuristic mutation/crossover；`alpha-diagnosis` 另起 rule-discovery 任务，并将规则注入主进化。 | 高 |
| LaSR: Symbolic Regression with a Learned Concept Library ([OpenReview](https://openreview.net/forum?id=B7S4jJGlvl), [Project](https://trishullab.github.io/lasr-web/)) | 2024 | 在符号回归中学习抽象文本概念库，并以一定概率用 LLMINIT/LLMMUTATE/LLMCROSSOVER 替代传统 GP 操作。 | 与“从高性能候选抽象概念，再用概念指导 mutation/crossover”相关。 | LaSR 的概念库加速符号回归；`alpha-diagnosis` 的规则库指导 coding/algorithm evolution 的停滞恢复。 | 中-高 |
| EoH-S: Evolution of Heuristic Set ([AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/41038)) | 2025/2026 | 设计互补 heuristic set，强调 diversity-aware population management。 | 与多规则集的互补性相关。 | 可借鉴规则集不要只追求单条最高分，而要覆盖不同失败模式。 | 中 |
| MEoH: Multi-objective Evolution of Heuristic ([arXiv](https://arxiv.org/abs/2409.16867), [AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/34922)) | 2025 | 将 LLM-based heuristic search 建模为多目标优化，同时考虑性能、效率、可扩展性，并用 dominance-dissimilarity 维护多样性。 | 与多目标 rule discovery 很相关：规则可能也需要覆盖性能、鲁棒性、复杂度等多个维度。 | MEoH 生成 Pareto 启发式；`alpha-diagnosis` 可借鉴 Pareto/diversity 思路来筛选互补诊断规则。 | 中-高 |
| MCTS-AHD ([PMLR](https://proceedings.mlr.press/v267/zheng25o.html), [OpenReview](https://openreview.net/forum?id=Do1OdZzYHr)) | 2025 | 用 Monte Carlo Tree Search 组织 LLM 生成的 heuristics，避免固定种群过早收敛并更充分探索暂时低分但有潜力的分支。 | 与“主进化搜索卡住/局部最优”问题直接相关。 | MCTS-AHD 通过改变搜索结构缓解停滞；`alpha-diagnosis` 通过轨迹诊断规则来恢复停滞。 | 中 |
| AutoMOAE | 2025/2026 | 面向多目标需求自动进化算法，LLM 动态合成带分析模块的 crossover 和 mutation operators，减少无效优化步骤。 | 是“算子 agent”方向的典型例子：LLM 不仅生成候选，还生成/定制变异和交叉算子。 | AutoMOAE 的贡献在 operator synthesis；`alpha-diagnosis` 可被定位为 operator-independent 的诊断指导层。 | 中 |
| A2DEPT: Automated Algorithm Design via Evolutionary Program Trees ([arXiv](https://arxiv.org/abs/2604.24043)) | 2026 | 用 evolutionary program trees 进行完整 solver program 的语义编辑和可执行性检查，突破只优化局部 scoring/priority function 的限制。 | 与“从 component-level heuristic tuning 走向 system-level algorithm redesign”相关。 | A2DEPT 直接编辑完整算法程序；`alpha-diagnosis` 发现能指导系统级重设计的诊断规则。 | 中-高 |
| BERT Mutation / Deep Learning-Based Operators for EAs ([arXiv](https://arxiv.org/abs/2407.10477)) | 2024/2025 | 用 BERT-style masked modeling 和深度学习设计 GP mutation / neural crossover 算子，让变异更可能提升 fitness。 | 可作为“学习型算子”背景，不限于 LLM。 | 它学习 mutation/crossover operator；`alpha-diagnosis` 学可解释规则，不替代具体算子。 | 低-中 |
| PAIR: LLM-Guided Selection Strategy for EAs ([arXiv](https://arxiv.org/abs/2503.03239)) | 2025 | 让 LLM 基于 genetic diversity、fitness、crossover compatibility 进行 mate selection。 | 与“LLM 作为 selection operator / pairing agent”直接相关。 | PAIR 改进选择算子；`alpha-diagnosis` 改进反馈与规则注入，可与选择算子正交结合。 | 中 |
| EASE: Effortless Algorithmic Solution Evolution ([arXiv](https://arxiv.org/abs/2509.18108)) | 2025 | 通用 test-evaluate-refine 框架，面向多种算法解的进化。 | 与通用 LLM+evaluator evolution 系统相关。 | 它泛化候选演化；`alpha-diagnosis` 是诊断层/规则层。 | 中 |
| BLADE: Benchmark suite for LLM-driven AAD ([arXiv](https://arxiv.org/abs/2504.20183)) | 2025 | 为 LLM-driven automated algorithm discovery 提供可复现 benchmark，比较 FunSearch、LLaMEA、EoH、ReEvo 等方法。 | 说明 AAD 已形成 benchmark 化研究生态。 | 可作为实验定位参考；`alpha-diagnosis` 若扩展到更多 AAD tasks，可用类似 benchmark 思路评估。 | 低 |
| Systematic Survey on LLMs for Evolutionary Optimization ([arXiv](https://arxiv.org/abs/2509.08269)) | 2025/2026 | 系统梳理 LLM 在进化优化中的角色，包括建模、算子生成、启发式设计、算法发现和求解器协同。 | 可作为算法进化方向的综述型引用。 | 不是具体方法，但有助于把 `alpha-diagnosis` 放到 LLM+EC 的 broader landscape 中。 | 低 |
| Evolutionary Computation and LLMs Survey ([arXiv](https://arxiv.org/abs/2505.15741)) | 2025 | 从双向协同角度综述 EC 如何优化 LLM，以及 LLM 如何自动设计 metaheuristic、operator、prompt 和架构。 | 适合支撑“算子 agent / LLM for EC”已成为独立方向。 | 综述型引用；用于 related work 背景而不是方法对比。 | 低 |

### 5.1 算子 Agent / LLM-as-Operator 方向小结

| 算子角色 | 代表工作 | 典型机制 | 与 `alpha-diagnosis` 的关系 |
| --- | --- | --- | --- |
| Crossover / recombination | LMX, LMEA, EoH, MEoH, LaSR, AutoMOAE | 将多个 parent code/thought/hypothesis 放入 prompt，让 LLM 合成继承优点的新 offspring。 | 这些工作改变“如何产生候选”；`alpha-diagnosis` 改变“生成候选时应遵守哪些从历史归纳出的诊断规则”。 |
| Mutation / local edit | FunSearch, LLaMEA, ReEvo, LaSR, BERT Mutation, LLaMEA-SAGE | 对已有程序/启发式做语义修改、结构修改或 masked replacement，并用 evaluation 反馈选择。 | `alpha-diagnosis` 可以为 mutation 提供高层失败模式，例如“哪些结构/行为应避免或加强”。 |
| Selection / pairing | LMEA, PAIR, MEoH, EoH-S | 根据 fitness、多样性、兼容性、Pareto dominance 或互补性选择 parent/elite。 | rule discovery 也可采用类似 diversity / complementarity 原则，避免只学到单一失败模式。 |
| Reflection / verbal gradients | ReEvo, GEPA, TextGrad, ProTeGi, LLaMEA-SAGE | 将相对性能差异、trace、结构特征或失败日志转成自然语言指导。 | 这是与 `alpha-diagnosis` 最接近的技术桥梁；区别在于 `alpha-diagnosis` 把反思显式变成可评估、可注入的规则集。 |
| Program-tree / system-level redesign | A2DEPT, AlphaEvolve, LLaMEA, EASE | 不只改局部 scoring function，而是改完整 solver/program/architecture。 | 支持将 `alpha-diagnosis` 定位为帮助 system-level algorithm evolution 跳出局部停滞的诊断模块。 |

## 6. 自动软件工程与 Coding Agent

| 工作 | 年份 | 核心思想 | 与 `alpha-diagnosis` 的关系 | 差异/可借鉴点 | 相似度 |
| --- | --- | --- | --- | --- | --- |
| SWE-bench ([arXiv](https://arxiv.org/abs/2310.06770)) | 2023 | 基于真实 GitHub issue 的软件工程 agent benchmark。 | 为 coding agent 评测提供背景。 | benchmark 不是方法；可作为 coding agent 场景的代表。 | 低 |
| SWE-agent ([arXiv](https://arxiv.org/abs/2405.15793), [GitHub](https://github.com/SWE-agent/SWE-agent)) | 2024 | 设计 agent-computer interface，让 LLM 通过 shell/editor 工具修复真实 issue。 | 与 `agentic-evolve` 中 coding agent 执行/迭代代码相关。 | SWE-agent 主要是单任务修复 agent；`alpha-diagnosis` 是跨尝试诊断与规则注入。 | 中 |
| OpenDevin / OpenHands ([GitHub](https://github.com/All-Hands-AI/OpenHands)) | 2024 | 开源通用软件工程 agent 平台，支持沙箱执行和多工具交互。 | 与工程化 coding agent 平台相关。 | 平台侧重任务执行；不专门做自动诊断规则发现。 | 低-中 |
| AutoCodeRover ([arXiv](https://arxiv.org/abs/2404.05427)) | 2024 | 结合代码搜索、fault localization 和 LLM patch generation 修复 GitHub issue。 | 与“诊断/定位后再生成代码”相关。 | AutoCodeRover 使用预定义定位流程；`alpha-diagnosis` 自动发现诊断规则。 | 中 |
| Agentless ([arXiv](https://arxiv.org/abs/2407.01489)) | 2024 | 非 agentic 的低成本 SWE-bench 流程：定位、修复采样、验证。 | 与“规则化 workflow 可能比自由 agent 稳定”相关。 | 可作为对照：`alpha-diagnosis` 可提升自由进化 loop 的稳定性。 | 中 |
| RepairAgent | 2024 | 用有限状态机模拟人类调试流程进行自动程序修复。 | 与结构化调试 workflow 相关。 | 依赖人工设计状态机；`alpha-diagnosis` 自动发现任务规则。 | 中 |
| PatchPilot ([OpenReview](https://openreview.net/forum?id=ybODpT8ydV)) | 2025/2026 | 低成本软件修复 agent，包含 reproduction、localization、generation、validation、refinement。 | 与“明确的诊断-生成-验证-精炼阶段”相关。 | PatchPilot 的流程固定；`alpha-diagnosis` 在进化停滞时动态发现规则。 | 中 |
| Agentic Rubrics as Contextual Verifiers for SWE Agents ([arXiv](https://arxiv.org/abs/2601.04171)) | 2026 | 让 expert agent 在 repo 中收集上下文并生成结构化 rubric，用免执行 verifier 对多个 patch rollout 排序。 | 和 coding agent + rubric verifier 的交叉最贴近，可能是 reviewer 会追问的 2026 工作。 | 它的核心是 execution-free verification/ranking；`alpha-diagnosis` 的核心是 trajectory-based diagnosis 与 rule-guided resume。 | 高 |
| SWE-EVO: Benchmarking Coding Agents in Long-Horizon Software Evolution Scenarios ([arXiv](https://arxiv.org/abs/2512.18470)) | 2025/2026 | 用 release notes 和版本演化任务构造长程软件演化 benchmark，要求 agent 跨多文件、多步骤改代码。 | 说明 coding agent 评测正从单 issue 修复转向长期软件演化。 | SWE-EVO 是 benchmark；可用来论证 `alpha-diagnosis` 这类跨尝试经验积累/诊断机制对 long-horizon evolution 更必要。 | 中 |
| Demystifying LLM-Based Software Engineering Agents ([PDF](https://lingming.cs.illinois.edu/publications/fse2025.pdf)) | 2025 | 分析 SWE agent 的设计空间、成本、稳定性和 benchmark 表现。 | 可作为 coding agent 背景综述。 | 非具体方法，但适合说明 agentic coding 的挑战。 | 低 |

## 7. 2026 年相关工作趋势与 novelty 压力

| 趋势 | 代表工作 | 对 `alpha-diagnosis` 的影响 | 写作建议 |
| --- | --- | --- | --- |
| Rubric 从人工静态标准走向自动、动态、可训练 | Dynamic Rubrics, Rubric-ARM, CDRRM, EvoLM, EvoRubric | “自动生成规则/rubric”本身已经不够新。 | 强调 `alpha-diagnosis` 的规则是从主任务 trajectory archive 中发现的诊断规则，目标是干预搜索，而不是单纯提升 judge。 |
| Evaluator 与 generator 共同演化 | Rubric-ARM, EvoLM, EvoRubric, SCORE | reviewer 可能会问你们是不是 evaluator-generator co-evolution 的一个应用。 | 区分“参数训练中的共同演化”和“外部 coding evolution loop 中的停滞恢复机制”。 |
| SWE agent 的 verifier 变成结构化、上下文相关 rubric | Agentic Rubrics | 这是与 coding agent 场景最接近的 2026 工作。 | 强调 Agentic Rubrics 生成 repo-grounded verifier 用于 patch 排序；`alpha-diagnosis` 生成历史轨迹驱动的诊断规则，用于继续产生候选。 |
| 从单轮任务转向长程演化任务 | SWE-EVO, AlphaEvolve, GEPA agent architecture discovery | 支持 `alpha-diagnosis` 的动机：长程搜索容易停滞，需要跨尝试经验压缩。 | 把 `alpha-diagnosis` 定位为 long-horizon LLM code evolution 的 meta-diagnostic module。 |
| 反馈不再只是标量，而是可解释的 causal / contrastive factors | CDRRM, GEPA, TextGrad, ProTeGi | 与你们的 rule discovery 很契合，但也增加相似度压力。 | 用“规则发现任务有自己的 evaluator，并输出可注入规则集”来区分普通 reflection。 |
| LLM 从 candidate generator 变成 operator designer | LMX, LMEA, PAIR, AutoMOAE, LLaMEA-SAGE, A2DEPT | 算法发现领域已经不只让 LLM 写候选，还让 LLM 设计 selection/crossover/mutation/search structure。 | 强调 `alpha-diagnosis` 与具体算子正交：它学习的是何种失败模式/诊断规则应约束下一轮搜索，可与任意 operator agent 组合。 |

## 8. 与 `alpha-diagnosis` 最接近的工作对比矩阵

| 对比维度 | Reflexion | GEPA | Eureka | FunSearch / AlphaEvolve | Rubric co-evolution 系列 | Agentic Rubrics | `alpha-diagnosis` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 优化对象 | agent memory/reflection | prompt/code/config 文本 | reward code | algorithm/program candidate | rubric generator / judge / policy | SWE patch verifier rubric | diagnostic rules + 主任务 prompt injection |
| 反馈来源 | 环境标量/文本反馈 | full execution traces + scores | RL rollout score + reflection | evaluator score | preference pairs、judge/meta-judge、temporal contrast | repo context + candidate patches | 主任务 archive、attempt score、trajectory artifacts |
| 中间知识形式 | 自由文本 reflection | mutation rationale / prompt variants | reward function code | candidate program | rubric criteria / rubric memory | 结构化 `rubrics.yaml` | 可解释诊断规则集 |
| 是否另起 discovery loop | 否 | 通常否，直接优化候选 | 否，直接进化 reward | 否，直接进化程序 | 通常是训练内交替优化 | 是，但服务 verifier 构建 | 是，主任务停滞后启动 rule-discovery 任务 |
| 是否训练模型 | 否 | 否 | 否 | 否 | 通常会训练 | 否或可训练 | 否 |
| 是否面向 coding/algorithm evolution | 部分 | 是 | reward code 是 | 是 | 通常不是 SWE/code evolution 主场景 | 是 | 是 |
| 与本工作的雷同风险 | 中 | 高 | 中-高 | 中-高 | 高 | 高 | - |
| 关键区分句 | reflection 不经过规则发现评估 | 直接演化文本参数，不把诊断规则作为独立可复用对象 | 发现 reward 而非诊断规则 | 发现程序而非发现反馈规则 | 改进 judge/rubric 或 policy 训练，而非恢复外部进化 loop | 生成 patch verifier，而非从历史进化轨迹发现搜索干预规则 | 停滞检测 → 轨迹规则发现 → 规则注入 → 继续主进化 |

## 9. 可写进论文的 Related Work 组织建议

| 段落 | 建议内容 | 重点引用 |
| --- | --- | --- |
| LLM feedback and self-improvement | 从 Self-Refine、Reflexion、Constitutional AI/RLAIF 引出自然语言反馈可以作为“semantic gradient”。 | Self-Refine, Reflexion, Constitutional AI, Self-Rewarding |
| Verifiers and evaluators | 介绍 LLM-as-a-Judge、CriticGPT、V-STaR、DeepSeek-R1/RLVR，说明可靠 feedback/verifier 对自动改进的重要性。 | G-Eval, Prometheus 2, CriticGPT, V-STaR, DeepSeek-R1, Agentic Rubrics |
| Rubric and criteria learning | 讨论 rubric 从人工标准走向自动生成、动态生成、contrastive synthesis、rubric/policy co-evolution。 | FLASK, Dynamic Rubrics, Rubric-RM, Rubric-ARM, CDRRM, EvoLM, EvoRubric |
| Algorithm discovery with LLMs | 说明 LLM+evaluator+evolution 已能发现程序、算法、reward 和 heuristic，并且 LLM 正在从 candidate generator 扩展为 selection/crossover/mutation/operator designer。 | FunSearch, AlphaEvolve, Eureka, LMX, LMEA, EoH, ReEvo, LLaMEA, MEoH, MCTS-AHD, A2DEPT |
| Coding agents and software evolution | 介绍 SWE-agent、OpenHands、AutoCodeRover、Agentless、Agentic Rubrics、SWE-EVO 等，说明真实代码环境中的反馈、验证和长程演化挑战。 | SWE-agent, OpenHands, AutoCodeRover, Agentless, PatchPilot, Agentic Rubrics, SWE-EVO |
| 本文定位 | 强调本工作不是再做一个 candidate generator、judge 或 rubric reward model，而是将历史失败/成功轨迹蒸馏成可解释诊断规则，并把规则回注进停滞的代码/算法进化 loop。 | 对比 Reflexion、GEPA、Eureka、EvoLM/EvoRubric、Agentic Rubrics |

## 10. 可直接使用的英文 Related Work 表述草稿

| 主题 | 草稿 |
| --- | --- |
| Feedback-driven self-improvement | Prior work has shown that natural-language feedback can serve as a semantic learning signal for LLM agents. Self-Refine iteratively critiques and revises a single model output, while Reflexion converts scalar or textual environment feedback into verbal reflections stored in agent memory. In contrast, our method does not merely append free-form reflections to the next attempt. It launches a separate diagnostic rule discovery process over the accumulated trajectory archive and injects the resulting structured rules back into the primary evolution loop. |
| Verifier and evaluator learning | A growing body of work studies LLM-based judges, critics, and verifiers, including G-Eval, Prometheus, AUTO-J, CriticGPT, V-STaR, and rule-based verifiable rewards in RLVR systems such as DeepSeek-R1. These methods improve the reliability of evaluation or use verifiers to select among candidate outputs. Our approach is complementary: it discovers interpretable, task-specific diagnostic rules from previous attempts and uses them to steer future candidate generation rather than training a general-purpose verifier. |
| Algorithm discovery and evolution | FunSearch and AlphaEvolve demonstrate that LLMs paired with automatic evaluators can evolve programs and discover algorithms, while Eureka, LLaMEA, and EoH extend this paradigm to reward functions and metaheuristics. Our work operates at a meta level within such evolutionary loops: instead of evolving only task solutions, it evolves diagnostic knowledge about why previous solutions succeeded or failed, then feeds that knowledge back into subsequent search. |
| Rubric learning | Recent work on dynamic rubric generation and rubric-based reward modeling automatically constructs evaluation criteria to improve LLM-as-a-Judge systems. Our diagnostic rules resemble rubrics in that they are natural-language, interpretable criteria, but they are optimized for intervention: the rules are injected into the generator's prompt to change the trajectory of future evolution, not only to score completed outputs. |
| 2026 rubric co-evolution contrast | Concurrent 2026 work such as Rubric-ARM, EvoLM, EvoRubric, CDRRM, and Agentic Rubrics shows a rapid move from static evaluators toward dynamically generated, context-specific rubrics. These systems primarily use rubrics as reward-model inputs, co-training signals, or execution-free verifiers. In contrast, our rules are discovered from the accumulated trajectory archive of an ongoing code-evolution process and are used as a recovery mechanism when the primary search becomes stuck. |

## 11. 推荐重点引用清单

| 优先级 | 引用 | 为什么重要 |
| --- | --- | --- |
| 必引 | Reflexion | 最直接的“从失败轨迹生成语言反馈并重试”的先驱。 |
| 必引 | GEPA | 与“trace-level natural language diagnosis + evolutionary text optimization”非常接近，需要正面对比。 |
| 必引 | FunSearch / AlphaEvolve | `agentic-evolve` 所处的 LLM algorithm discovery/evolution 主线。 |
| 必引 | Eureka | 自动发现 reward/evaluator-like code，与自动发现 feedback/rules 相邻。 |
| 必引 | Dynamic Rubrics / Rubric-ARM / EvoLM / EvoRubric | 与自动生成、优化和共同演化 evaluation criteria/rubrics 最接近，尤其要处理 2026 年 novelty 压力。 |
| 必引 | Agentic Rubrics | coding agent 场景下自动生成结构化 verifier/rubric，和你们的 rule injection 最容易被比较。 |
| 强烈建议 | TextGrad / ProTeGi | 支撑“自然语言反馈作为梯度/诊断信号”的说法。 |
| 强烈建议 | CDRRM / CriticGPT / V-STaR | 支撑“contrastive diagnostic factors、专门 verifier/critic 能提升代码与推理反馈质量”的说法。 |
| 可选 | SWE-agent / AutoCodeRover / Agentless / SWE-EVO | 用于说明 coding agent 环境、验证、修复工作流和长程软件演化场景。 |
| 可选 | Prometheus 2 / AUTO-J / G-Eval | 用于 evaluator/judge 背景。 |
| 可选 | LLaMEA / EoH / EASE | 用于算子/heuristic/algorithm design agent 背景。 |

