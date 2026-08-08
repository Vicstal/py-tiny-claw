# internal/context/skill.py
# 第 10 章：SkillLoader —— 扫描 .claw/skills/ 下的 SKILL.md，将"外挂技能"注入 System Prompt。
import os
from dataclasses import dataclass


@dataclass
class Skill:
    name: str = ""
    description: str = ""
    body: str = ""


class SkillLoader:
    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def load_all(self) -> str:
        skill_base_dir = os.path.join(self.work_dir, ".claw", "skills")

        if not os.path.exists(skill_base_dir):
            return ""

        builder: list[str] = []
        builder.append("\n### 可用专业技能 (Agent Skills)\n")
        builder.append("以下是你拥有的标准化外挂技能，请在符合 description 描述的场景下严格遵循其正文指令：\n\n")

        # 递归遍历技能目录，收集所有 SKILL.md（对应 Go 的 filepath.WalkDir）
        try:
            for root, _dirs, files in os.walk(skill_base_dir):
                for file_name in files:
                    if file_name == "SKILL.md":
                        path = os.path.join(root, file_name)
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                content = f.read()
                        except OSError:
                            continue

                        skill = parse_skill_md(content)

                        builder.append(f"#### 技能名称: {skill.name}\n")
                        builder.append(f"**触发条件**: {skill.description}\n\n")
                        builder.append("**执行指南**:\n")
                        builder.append(skill.body)
                        builder.append("\n\n---\n")
        except OSError:
            return ""

        result = "".join(builder)
        # 如果没有实际加载到任何技能（只有开头两行说明），返回空
        if len(result) < 50:
            return ""

        return result


def parse_skill_md(content: str) -> Skill:
    """解析 SKILL.md 的 YAML frontmatter（只提取 name / description 两个字段）"""
    skill = Skill(
        name="Unknown Skill",
        description="No description provided.",
        body=content,
    )

    if content.startswith("---\n") or content.startswith("---\r\n"):
        parts = content.split("---", 2)
        if len(parts) == 3:
            frontmatter = parts[1]
            skill.body = parts[2].strip()

            for line in frontmatter.split("\n"):
                line = line.strip()
                if line.startswith("name:"):
                    skill.name = line.removeprefix("name:").strip()
                elif line.startswith("description:"):
                    skill.description = line.removeprefix("description:").strip()

    return skill
