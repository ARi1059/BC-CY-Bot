"""用户侧报销 wizard 的 callback_data 命名空间。"""

# 入口
REI_USER_START = "rei:start"      # 欢迎卡片或 /reimburse 入口

# Wizard 导航
REI_USER_CANCEL = "rei:cancel"
REI_USER_BACK = "rei:back"
REI_USER_CONFIRM_CANCEL = "rei:cc"
REI_USER_DISMISS = "rei:dm"

# 预览操作
REI_USER_PREVIEW_CONFIRM = "rei:pc"
REI_USER_PREVIEW_REDO = "rei:pr"

# 选老师（v1.0.0-beta.3 起，wizard 起点）
REI_USER_PICK_TEACHER_PREFIX = "rei:t:"   # + teacher_id
REI_USER_PICK_TEACHER_PAGE_PREFIX = "rei:tp:"  # + page (老师列表翻页)


def parse_pick_teacher(d: str) -> int | None:
    if not d.startswith(REI_USER_PICK_TEACHER_PREFIX):
        return None
    try:
        return int(d[len(REI_USER_PICK_TEACHER_PREFIX):])
    except ValueError:
        return None


def parse_teacher_page(d: str) -> int | None:
    if not d.startswith(REI_USER_PICK_TEACHER_PAGE_PREFIX):
        return None
    try:
        return int(d[len(REI_USER_PICK_TEACHER_PAGE_PREFIX):])
    except ValueError:
        return None
