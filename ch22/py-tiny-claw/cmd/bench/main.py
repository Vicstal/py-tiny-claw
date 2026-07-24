# cmd/bench/main.py
# 对应 Go 版: cmd/bench/main.go
# 第 20 章：微型评测集入口。
# （Go 版的第二个用例是 math.go + go test；Python 版对应改为 calc.py + unittest。
#   之所以不叫 math.py，是为了避免与 Python 标准库 math 模块重名导致测试环境崩溃。）
# 运行方式（在 py-tiny-claw 目录下）: ZHIPU_API_KEY=xxx python -m cmd.bench.main
import logging
import os
import sys

from internal.eval.benchmark import BenchmarkRunner, TestCase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量进行跑分测试")

    # 构建一套微型评测集
    testcases = [
        TestCase(
            id="test_001_edit",
            name="测试模糊替换工具的准确性",
            # 准备靶机：生成一个有错误的 json 文件
            setup_script="""echo '{"name": "tiny-claw", "version": "v1.0.0"}' > config.json""",
            # 考题：要求修改版本号
            task_prompt="当前目录下有一个 config.json。请你使用 edit_file 工具，将其中的 version 从 v1.0.0 改为 v2.0.0。不要做其他多余操作。",
            # 判卷脚本：使用 grep 检查文件是否包含 v2.0.0
            validate_script="""grep '"version": "v2.0.0"' config.json""",
        ),
        TestCase(
            id="test_002_code_gen",
            name="测试代码阅读与创建新文件的综合能力",
            # 准备靶机：生成一个简单的乘法函数
            setup_script="""printf 'def multiply(a, b):\\n    return a * b\\n' > calc.py""",
            # 考题：要求 Agent 根据刚才的代码，自己去写一份单元测试
            task_prompt="当前目录下有一个 calc.py。请你仔细阅读它，然后在同级目录下，帮我写一个规范的单元测试文件 test_calc.py，用来测试 multiply 函数。请务必包含正常的测试用例。",
            # 判卷脚本：直接运行 unittest！如果不通过则直接 0 分。
            validate_script="python3 -m unittest discover -v",
        ),
    ]

    # 启动跑分执行器！
    # 我们选用国内极其廉价但能力不错的 glm-4.5-air 跑分，省点钱。
    runner = BenchmarkRunner("glm-4.5-air")
    runner.run_suite(testcases)


if __name__ == "__main__":
    main()
