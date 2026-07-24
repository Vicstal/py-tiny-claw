# 对应 Go 版: workspace/auth.go（供第 14 章自愈实验使用的示例文件）
# 注意：这里故意没有 "# 鉴权入口函数" 这行注释，与指令中给出的 old_text 不一致，
# 用来诱发 edit_file 的匹配失败。
def login(user):
    # 检查用户名
    if user == "admin":
        return True
    return False
