# py-tiny-claw

极客时间课程《从 0 开始构建 Agent Harness》的 Python 配套代码。

课程原版以 Go 实现，本仓库将每一章的核心机制等价翻译为 Python，保持相同的目录结构与演进路径，让 Python 开发者能够跟着课程一步步手搓一个生产可用的 AI Agent 框架。

---

## 这个项目做了什么

**tiny-claw** 是一个从零开始、逐章累积的 AI Agent 运行时（Harness）。

你会看到一个最初只有十几行代码的入口文件，如何一章一章地长成一个具备以下能力的完整 Agent 框架：

- **Reason-Act-Observe 主循环**：模型思考 → 调用工具 → 观察结果 → 再思考，直到任务完成
- **慢思考（Thinking Phase）**：强制模型在行动前先输出计划，抑制幻觉
- **真实大模型接入**：同时支持 Anthropic Claude 和 OpenAI 兼容端点（如智谱 GLM）
- **工具系统**：`read_file`、`write_file`、`bash`、`edit_file`（带四级模糊替换），可热插拔
- **并发工具执行**：多个工具调用通过 `ThreadPoolExecutor` 并行运行，减少等待
- **动态 System Prompt**：`PromptComposer` 在每轮运行时合成提示词，支持 `AGENTS.md` 和 `SKILL.md` 技能加载
- **多会话隔离**：`Session` 独立管理每个对话的上下文与短期记忆
- **上下文压缩（Compactor）**：防止长对话撑爆 token 限制
- **Plan Mode**：将计划写入 `PLAN.md` / `TODO.md`，支持断点续传
- **错误自愈（RecoveryManager）**：分析报错特征，自动注入对应的修复指引
- **死循环探测（ReminderInjector）**：识别 Agent 陷入重复行为并强力干预
- **人工审批（Feishu）**：通过飞书机器人挂起工具调用，等待人工 approve/reject 后继续
- **子智能体（spawn_subagent）**：在只读沙箱中派生子 Agent，有轮数上限
- **成本观测（CostTracker）**：装饰器包裹 Provider，自动统计每次调用的 token 用量
- **链路追踪**：极简 Trace/Span，输出到 `.claw/traces/*.json`
- **自动化评测（BenchmarkRunner）**：给 Agent 出题、跑分、汇报结果

---

## 各章内容速览

| 章节 | 新增 / 变更内容 |
|------|----------------|
| ch01 | 项目骨架，仅入口文件 |
| ch02 | Reason-Act-Observe 主循环（mock Provider / Registry） |
| ch03 | 慢思考 Thinking Phase（剥夺工具强制规划） |
| ch04 | 接入真实大模型：`provider/claude.py`、`provider/openai.py`（智谱兼容端点） |
| ch05 | Registry 真实实现 + 第一个工具 `read_file` |
| ch06 | `write_file`、`bash` 工具（30s 超时保护） |
| ch07 | `edit_file` 工具 + 四级模糊替换 `fuzzy_replace` |
| ch08 | 工具并发执行（Go goroutine → Python `ThreadPoolExecutor`） |
| ch09 | 飞书机器人 + `Reporter` 事件外发接口 |
| ch10 | `PromptComposer` 动态 System Prompt + `AGENTS.md` + `SKILL.md` 技能加载 |
| ch11 | `Session` 多会话隔离 + 短期工作记忆（截断孤儿保护） |
| ch12 | `Compactor` 上下文压缩（防 OOM） |
| ch13 | Plan Mode 状态外部化（`PLAN.md` / `TODO.md` 断点续传）+ 消息合规合并 |
| ch14 | `RecoveryManager` 报错特征分析与救援指南注入 |
| ch15 | `ReminderInjector` 死循环探测与强力干预 |
| ch16 | Registry Middleware + 飞书人工审批（approve/reject 挂起唤醒） |
| ch17 | `spawn_subagent` 子智能体（只读沙箱 + 轮数上限） |
| ch18 | `CostTracker` 成本观测（装饰器包裹 Provider）+ Usage 统计 |
| ch19 | 极简链路追踪 Trace/Span（导出 `.claw/traces/*.json`） |
| ch20 | `BenchmarkRunner` 自动化评测框架 + `cmd/bench` 跑分入口 |
| ch21 | 最终 CLI 形态（`-prompt` / `-dir` / `-session` 参数 + 全息监控） |
| ch22 | AgentOps 场景：运维黑名单扩展 + Reporter 上下文传递 + 引擎工厂 |

---

## 快速开始

每章都是独立可运行的完整项目，进入对应目录后：

```bash
cd ch05/py-tiny-claw
pip install -r requirements.txt        # ch04 起需要；ch01–ch03 纯标准库
export ANTHROPIC_API_KEY=你的密钥      # 或 ZHIPU_API_KEY（ch04 openai 兼容端点）
python -m cmd.claw.main
```

**ch13 / ch21** 通过命令行传入任务：

```bash
python -m cmd.claw.main -prompt "帮我写一个冒泡排序，保存到 sort.py"
```

**ch20** 跑分入口：

```bash
python -m cmd.bench.main
```

**ch09 / ch16 / ch22**（飞书相关）还需要：

```
FEISHU_APP_ID
FEISHU_APP_SECRET
FEISHU_ENCRYPT_KEY     # 可选
FEISHU_VERIFY_TOKEN    # 可选
```

---

## 目录结构

每章遵循统一的包结构：

```
chXX/py-tiny-claw/
├── cmd/
│   └── claw/
│       └── main.py        # 入口
├── internal/
│   ├── engine/
│   │   └── loop.py        # 主循环
│   ├── provider/
│   │   └── interface.py   # LLM Provider 抽象
│   ├── schema/
│   │   └── message.py     # 消息数据结构
│   └── tools/
│       └── registry.py    # 工具注册中心
└── requirements.txt       # ch04 起存在
```

---

## Go → Python 对应关系

| Go 概念 | Python 对应实现 |
|---------|----------------|
| `struct` + JSON tag | `@dataclass`（`internal/schema/message.py`） |
| `interface`（隐式实现） | `abc.ABC` 抽象基类 |
| `(result, error)` 返回值 | 正常返回 / 抛异常，由 Registry 统一捕获转为 `ToolResult(is_error=True)` |
| goroutine + `sync.WaitGroup` | `concurrent.futures.ThreadPoolExecutor` |
| channel（审批挂起/唤醒） | `queue.Queue(maxsize=1)` 阻塞 `get()` |
| `context.WithValue` 传递 Span/Reporter | 标准库 `contextvars`（并发执行时 `copy_context()` 继承） |
| `sync.Mutex` / `sync.RWMutex` | `threading.Lock` |
| `NewXxx()` 构造函数 | `new_xxx()` 工厂函数（或直接类构造） |
| `log.Printf` | `logging`（同款日期时间前缀格式） |
| anthropic-sdk-go / openai-go | `anthropic` / `openai` 官方 Python SDK |
| `net/http` + httpserverext | 标准库 `http.server` + 手工适配 `lark.RawRequest` |
