"""邀请人面板的 callback_data 命名空间。"""

INV_PANEL = "ipanel:panel"
INV_PANEL_BACK = "ipanel:back"
INV_PANEL_PENDING = "ipanel:pending"
INV_PANEL_STATS = "ipanel:stats"
INV_PANEL_REPOST_PREFIX = "ipanel:repost:"  # + app_id


def parse_repost(d: str) -> int | None:
    if not d.startswith(INV_PANEL_REPOST_PREFIX):
        return None
    try:
        return int(d[len(INV_PANEL_REPOST_PREFIX):])
    except ValueError:
        return None
