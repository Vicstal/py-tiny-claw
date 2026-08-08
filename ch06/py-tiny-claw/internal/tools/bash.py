# internal/tools/bash.py
# 对应 Go 版: internal/tools/bash.go
# 第 6 章：bash 工具 —— Agent 最强大的"万能手"，可以执行任意 shell 命令。
import json
import subprocess

from internal.schema.message import ToolDefinition
from internal.tools.registry import BaseTool


class BashTool(BaseTool):
    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def name(self) -> str:
        return "bash"

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name(),
            description="在当前工作区执行任意的 bash 命令。支持链式命令(如 &&)。返回标准输出(stdout)和标准错误(stderr)。",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 bash 命令",
                    },
                },
                "required": ["command"],
            },
        )

    def execute(self, args: str) -> str:
        try:
            input_args = json.loads(args)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"参数解析失败: {e}") from e

        # 30 秒超时保护，防止模型执行的命令把引擎挂死
        """
          Python 的 subprocess.run(...) 函数会向操作系统发起请求，创建一个独立的子进程来运行指定程序。具体各个参数的作用如下：                                          
                                                                                                                                                                
        1. ["bash", "-c", command]                                                                                                                                    
            • 这是真正执行命令的方式。它并不是直接把命令交给系统底层，而是启动系统的 bash 解释器进程。                                                                
            • -c 参数告诉 Bash：“请把接下来的字符串 command 当作一条或一组完整的 Bash 脚本指令来解析和执行”。                                                         
            • 好处：这样使得 command 可以支持重定向（如 >）、管道（如 |）、变量以及链式组合命令（如 && 或 ;）。                                                       
        2. cwd=self.work_dir                                                                                                                                          
            • 指定命令执行的工作目录（Working Directory）。比如设为 /path/to/project，那么命令中的相对路径都会在此目录下生效。                                        
        3. capture_output=True                                                                                                                                        
            • 告诉 Python 截获该子进程的标准输出（stdout）和标准错误（stderr），而不是直接打印在控制台上。                                                            
        4. text=True                                                                                                                                                  
            • 自动将捕获到的二进制字节流（bytes）按照 UTF-8 编码转换成 Python 的字符串（str），方便后续处理。                                                         
        5. timeout=30                                                                                                                                                 
            • 超时保护机制：如果命执行超过 30 秒（例如死循环或交互式卡住），subprocess 会自动杀死该 Bash 子进程并抛出 subprocess.TimeoutExpired 异常。
        """
        try:
            proc = subprocess.run(
                ["bash", "-c", input_args.get("command", "")],
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            # stdout/stderr 合并输出（对应 Go 的 CombinedOutput）
            partial = (e.stdout or "") + (e.stderr or "")
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", errors="replace")
            return partial + "\n[警告: 命令执行超时(30s)，已被系统强制终止。]"

        output_str = proc.stdout + proc.stderr

        if proc.returncode != 0:
            return f"执行报错: exit status {proc.returncode}\n输出:\n{output_str}"

        if output_str == "":
            return "命令执行成功，无终端输出。"

        MAX_LEN = 8000
        if len(output_str) > MAX_LEN:
            return f"{output_str[:MAX_LEN]}\n\n...[终端输出过长，已截断至前 {MAX_LEN} 字节]..."

        return output_str
