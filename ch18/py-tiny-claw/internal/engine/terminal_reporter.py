# internal/engine/terminal_reporter.py
# 对应 Go 版: internal/engine/terminal_reporter.go
# 第 10 章：终端版 Reporter —— 在本地调试时直接把过程打印到终端。
from internal.engine.reporter import Reporter


class TerminalReporter(Reporter):
    def on_thinking(self):
        print("\n[🤔 思考中] 模型正在推理...")

    def on_tool_call(self, tool_name: str, args: str):
        print(f"[🛠️ 调用工具] {tool_name}")
        # 清理参数中的换行符和特殊字符
        display_args = args.replace("\n", "\\n").replace("\r", "\\r")
        if len(display_args) > 150:
            display_args = display_args[:150] + "... (已截断)"
        print(f"   参数: {display_args}")

    def on_tool_result(self, tool_name: str, result: str, is_error: bool):
        if is_error:
            print(f"[❌ 执行失败] {tool_name}")
            # 显示错误信息
            if result != "":
                print(f"   错误: {result}")
        else:
            print(f"[✅ 执行成功] {tool_name}")

    def on_message(self, content: str):
        if content == "":
            return
        print(f"\n🤖 Agent 回复:\n{content}\n")


def new_terminal_reporter() -> TerminalReporter:
    """对应 Go 版的 NewTerminalReporter 构造函数"""
    return TerminalReporter()
