# py-tiny-claw

一个轻量级 AI Agent 运行时框架，支持以下能力：

- **Reason-Act-Observe 主循环**：模型思考 → 调用工具 → 观察结果 → 再思考，直至任务完成
- **慢思考（Thinking Phase）**：强制模型在行动前输出计划，抑制幻觉
- **多 LLM 后端**：支持 Anthropic Claude 和 OpenAI 兼容端点（如智谱 GLM）
- **可插拔工具系统**：内置 `read_file`、`write_file`、`bash`、`edit_file`（含四级模糊替换）
- **并发工具执行**：多个工具调用通过 `ThreadPoolExecutor` 并行运行
- **动态 System Prompt**：运行时合成提示词，支持 `AGENTS.md` / `SKILL.md` 技能热加载
- **多会话隔离**：每个会话独立管理上下文与短期记忆
- **上下文压缩（Compactor）**：自动压缩长对话，防止超出 token 上限
- **Plan Mode**：将计划写入 `PLAN.md` / `TODO.md`，支持中断后断点续传
- **错误自愈（RecoveryManager）**：分析报错特征，自动注入对应修复指引
- **死循环探测（ReminderInjector）**：识别重复行为并强力干预
- **人工审批**：通过飞书机器人挂起工具调用，等待 approve/reject 后继续执行
- **子智能体（spawn_subagent）**：在只读沙箱中派生子 Agent，有最大轮数限制
- **成本观测（CostTracker）**：自动统计每次 LLM 调用的 token 用量
- **链路追踪**：极简 Trace/Span，输出到 `.claw/traces/*.json`
- **自动化评测（BenchmarkRunner）**：给 Agent 出题、跑分、汇报结果

## 快速开始

```bash
cd ch21/py-tiny-claw
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key
python -m cmd.claw.main -prompt "帮我写一个冒泡排序，保存到 sort.py"
```

飞书审批相关功能还需要：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`（可选 `FEISHU_ENCRYPT_KEY`、`FEISHU_VERIFY_TOKEN`）。

评测入口：

```bash
python -m cmd.bench.main
```

## 目录结构

```
chXX/py-tiny-claw/
├── cmd/claw/main.py           # 入口
├── internal/
│   ├── engine/loop.py         # 主循环
│   ├── provider/              # LLM 后端抽象
│   ├── schema/message.py      # 消息数据结构
│   └── tools/registry.py      # 工具注册中心
└── requirements.txt
```
