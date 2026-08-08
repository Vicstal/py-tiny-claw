# cmd/claw/main.py
# 第 1 章：搭建项目骨架。此时只有一个入口文件，各模块尚未实现。
import logging

# 配置 log，模拟 Go 标准库 log 的 "日期 时间 消息" 输出格式
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")
log = logging.getLogger(__name__)


def main():
    print("🚀 欢迎来到 py-tiny-claw 引擎启动序列")

    # TODO: 1. 初始化模型 Provider (大脑)
    # provider = ZhipuClaudeProvider(...)

    # TODO: 2. 初始化 Tool Registry (手脚)
    # registry = Registry()
    # registry.register(BashTool())

    # TODO: 3. 初始化上下文管理器 (内存管理器)
    # ctx_manager = context.Manager(...)

    # TODO: 4. 组装并启动核心 Engine (操作系统心脏)
    # engine = AgentEngine(provider, registry, ctx_manager)

    # print("开始执行任务...")
    # try:
    #     engine.run("帮我检查一下当前目录下的文件并输出一个 README.md 大纲")
    # except Exception as e:
    #     sys.exit(f"引擎运行崩溃: {e}")

    log.info("骨架搭建完毕，等待各模块注入！")


if __name__ == "__main__":
    main()
