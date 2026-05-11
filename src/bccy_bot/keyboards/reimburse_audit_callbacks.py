"""管理员侧报销审核 callback_data 命名空间。"""

REV_APPROVE_PREFIX = "rev:approve:"
REV_REJECT_PREFIX = "rev:reject:"
REV_REJECT_REASON_PREFIX = "rev:rreason:"
REV_REJECT_SKIP_PREFIX = "rev:rskip:"
REV_VIEW_PREFIX = "rev:view:"
REV_CANCEL_WAIT_PREFIX = "rev:cwait:"
REV_RESEND_PAYMENT_PREFIX = "rev:rsend:"  # 从管理面板"待付款"列表补发口令


def _parse_int_suffix(d: str, prefix: str) -> int | None:
    if not d.startswith(prefix):
        return None
    try:
        return int(d[len(prefix):])
    except ValueError:
        return None


def parse_approve(d: str) -> int | None: return _parse_int_suffix(d, REV_APPROVE_PREFIX)
def parse_reject(d: str) -> int | None: return _parse_int_suffix(d, REV_REJECT_PREFIX)
def parse_reject_reason(d: str) -> int | None: return _parse_int_suffix(d, REV_REJECT_REASON_PREFIX)
def parse_reject_skip(d: str) -> int | None: return _parse_int_suffix(d, REV_REJECT_SKIP_PREFIX)
def parse_view(d: str) -> int | None: return _parse_int_suffix(d, REV_VIEW_PREFIX)
def parse_cancel_wait(d: str) -> int | None: return _parse_int_suffix(d, REV_CANCEL_WAIT_PREFIX)
def parse_resend_payment(d: str) -> int | None: return _parse_int_suffix(d, REV_RESEND_PAYMENT_PREFIX)
