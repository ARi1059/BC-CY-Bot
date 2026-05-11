"""管理员面板的 callback_data 命名空间。

格式：admin:<module>[:<action>[:<arg>...]]
- 总长 <= 64 字节（Telegram 限制）
- module/action 用小写字母 + 下划线
- 数字 ID 作为 arg
"""

# 主面板
ADM_PANEL = "admin:panel"
ADM_BACK = "admin:back"

# === Groups ===
ADM_GRP_LIST = "admin:groups"
ADM_GRP_LIST_PREFIX = "admin:groups:p:"  # + page
ADM_GRP_ADD = "admin:groups:add"
ADM_GRP_REMOVE_PREFIX = "admin:groups:rm:"  # + id
ADM_GRP_REMOVE_CONFIRM_PREFIX = "admin:groups:rmc:"  # + id

# === Inviters ===
ADM_INV_LIST = "admin:inviters"
ADM_INV_LIST_PREFIX = "admin:inviters:p:"  # + page
ADM_INV_ADD = "admin:inviters:add"
ADM_INV_ADD_PICK_GRP_PREFIX = "admin:inviters:ag:"  # + group_id
ADM_INV_ADD_TOGGLE_MAT_PREFIX = "admin:inviters:am:"  # + material short code (b/g/r)
ADM_INV_ADD_SET_MODE_PREFIX = "admin:inviters:as:"  # + 'self' or 'deleg'
ADM_INV_ADD_CONFIRM = "admin:inviters:ac"
ADM_INV_ADD_CANCEL = "admin:inviters:ax"
ADM_INV_TOGGLE_PREFIX = "admin:inviters:tg:"  # + id
ADM_INV_REMOVE_PREFIX = "admin:inviters:rm:"  # + id
ADM_INV_REMOVE_CONFIRM_PREFIX = "admin:inviters:rmc:"  # + id

# === Blacklist ===
ADM_BL_LIST = "admin:bl"
ADM_BL_LIST_PREFIX = "admin:bl:p:"
ADM_BL_ADD = "admin:bl:add"
ADM_BL_REMOVE_PREFIX = "admin:bl:rm:"
ADM_BL_REMOVE_CONFIRM_PREFIX = "admin:bl:rmc:"

# === Admin management ===
ADM_MGMT_LIST = "admin:adm"
ADM_MGMT_ADD = "admin:adm:add"  # super only
ADM_MGMT_REMOVE_PREFIX = "admin:adm:rm:"  # super only
ADM_MGMT_REMOVE_CONFIRM_PREFIX = "admin:adm:rmc:"
ADM_MGMT_TRANSFER_PREFIX = "admin:adm:tr:"  # super only
ADM_MGMT_TRANSFER_CONFIRM_PREFIX = "admin:adm:trc:"

# === Channels ===
ADM_LOG_CHANNEL = "admin:lch"
ADM_LOG_CHANNEL_BIND = "admin:lch:bind"
ADM_LOG_CHANNEL_UNBIND = "admin:lch:unbind"
ADM_REPORT_CHANNEL = "admin:rch"
ADM_REPORT_CHANNEL_BIND = "admin:rch:bind"
ADM_REPORT_CHANNEL_UNBIND = "admin:rch:unbind"

# === System config (super only) ===
ADM_CONFIG = "admin:cfg"
ADM_CONFIG_EDIT_TTL = "admin:cfg:ttl"

# === Stats ===
ADM_STATS = "admin:stats"

# === Reimbursement (v2 §8.5) ===
ADM_REI = "admin:rei"
# Settings (super-only mutations)
ADM_REI_SETTINGS = "admin:rei:s"
ADM_REI_TOGGLE = "admin:rei:s:tog"
ADM_REI_SET_AMOUNT = "admin:rei:s:amt"
ADM_REI_SET_BUDGET = "admin:rei:s:bdg"
ADM_REI_RESET_REMAINING = "admin:rei:s:rst"
ADM_REI_SET_COOLDOWN = "admin:rei:s:cd"
ADM_REI_SET_RESET_DAY = "admin:rei:s:rd"
# Eligibility chats
ADM_REI_ELIG = "admin:rei:e"
ADM_REI_ELIG_ADD = "admin:rei:e:add"
ADM_REI_ELIG_REMOVE_PREFIX = "admin:rei:e:rm:"
ADM_REI_ELIG_REMOVE_CONFIRM_PREFIX = "admin:rei:e:rmc:"
# User overrides
ADM_REI_OVERRIDES = "admin:rei:o"
ADM_REI_OVERRIDE_ADD = "admin:rei:o:add"
ADM_REI_OVERRIDE_REMOVE_PREFIX = "admin:rei:o:rm:"
ADM_REI_OVERRIDE_REMOVE_CONFIRM_PREFIX = "admin:rei:o:rmc:"
# Lists
ADM_REI_PENDING_LIST = "admin:rei:plist"
ADM_REI_APPROVED_LIST = "admin:rei:alist"
ADM_REI_HISTORY_LIST = "admin:rei:hlist"
# Per-row actions
ADM_REI_RESEND_AUDIT_PREFIX = "admin:rei:rsau:"      # 重发审核材料
ADM_REI_RESEND_PAYMENT_PREFIX = "admin:rei:rspay:"   # 补发口令（重置 await 状态）


def parse_rei_elig_remove(d: str) -> int | None:
    return _parse_int_suffix(d, ADM_REI_ELIG_REMOVE_PREFIX)


def parse_rei_elig_remove_confirm(d: str) -> int | None:
    return _parse_int_suffix(d, ADM_REI_ELIG_REMOVE_CONFIRM_PREFIX)


def parse_rei_override_remove(d: str) -> int | None:
    return _parse_int_suffix(d, ADM_REI_OVERRIDE_REMOVE_PREFIX)


def parse_rei_override_remove_confirm(d: str) -> int | None:
    return _parse_int_suffix(d, ADM_REI_OVERRIDE_REMOVE_CONFIRM_PREFIX)


def parse_rei_resend_audit(d: str) -> int | None:
    return _parse_int_suffix(d, ADM_REI_RESEND_AUDIT_PREFIX)


def parse_rei_resend_payment(d: str) -> int | None:
    return _parse_int_suffix(d, ADM_REI_RESEND_PAYMENT_PREFIX)

# === 占位（后续里程碑接管）===
ADM_PENDING = "admin:pending"  # M3 已实现：跳到待审核列表
ADM_KEYS = "admin:keys"  # M8 实现

# 通用 dismiss（取消二次确认）
ADM_DISMISS = "admin:dismiss"


def _parse_int_suffix(data: str, prefix: str) -> int | None:
    if not data.startswith(prefix):
        return None
    try:
        return int(data[len(prefix):])
    except ValueError:
        return None


def _parse_str_suffix(data: str, prefix: str) -> str | None:
    if not data.startswith(prefix):
        return None
    return data[len(prefix):]


# 解析帮助
def parse_grp_list_page(d: str) -> int | None: return _parse_int_suffix(d, ADM_GRP_LIST_PREFIX)
def parse_grp_remove(d: str) -> int | None: return _parse_int_suffix(d, ADM_GRP_REMOVE_PREFIX)
def parse_grp_remove_confirm(d: str) -> int | None: return _parse_int_suffix(d, ADM_GRP_REMOVE_CONFIRM_PREFIX)

def parse_inv_list_page(d: str) -> int | None: return _parse_int_suffix(d, ADM_INV_LIST_PREFIX)
def parse_inv_add_pick_grp(d: str) -> int | None: return _parse_int_suffix(d, ADM_INV_ADD_PICK_GRP_PREFIX)
def parse_inv_add_toggle_mat(d: str) -> str | None: return _parse_str_suffix(d, ADM_INV_ADD_TOGGLE_MAT_PREFIX)
def parse_inv_add_set_mode(d: str) -> str | None: return _parse_str_suffix(d, ADM_INV_ADD_SET_MODE_PREFIX)
def parse_inv_toggle(d: str) -> int | None: return _parse_int_suffix(d, ADM_INV_TOGGLE_PREFIX)
def parse_inv_remove(d: str) -> int | None: return _parse_int_suffix(d, ADM_INV_REMOVE_PREFIX)
def parse_inv_remove_confirm(d: str) -> int | None: return _parse_int_suffix(d, ADM_INV_REMOVE_CONFIRM_PREFIX)

def parse_bl_list_page(d: str) -> int | None: return _parse_int_suffix(d, ADM_BL_LIST_PREFIX)
def parse_bl_remove(d: str) -> int | None: return _parse_int_suffix(d, ADM_BL_REMOVE_PREFIX)
def parse_bl_remove_confirm(d: str) -> int | None: return _parse_int_suffix(d, ADM_BL_REMOVE_CONFIRM_PREFIX)

def parse_adm_remove(d: str) -> int | None: return _parse_int_suffix(d, ADM_MGMT_REMOVE_PREFIX)
def parse_adm_remove_confirm(d: str) -> int | None: return _parse_int_suffix(d, ADM_MGMT_REMOVE_CONFIRM_PREFIX)
def parse_adm_transfer(d: str) -> int | None: return _parse_int_suffix(d, ADM_MGMT_TRANSFER_PREFIX)
def parse_adm_transfer_confirm(d: str) -> int | None: return _parse_int_suffix(d, ADM_MGMT_TRANSFER_CONFIRM_PREFIX)


# 材料短码（callback 长度优化）
MAT_CODE_MAP = {"b": "约课记录", "g": "上课手势", "r": "出击报告"}
MAT_TO_CODE = {v: k for k, v in MAT_CODE_MAP.items()}
