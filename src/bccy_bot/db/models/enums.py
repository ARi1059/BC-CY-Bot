"""枚举常量（统一以字符串落库，便于跨 PG/SQLite 兼容与运维肉眼可读）。"""

# applications.status
APP_STATUS_WIZARD = "wizard"
APP_STATUS_PENDING = "pending"
APP_STATUS_APPROVED = "approved"
APP_STATUS_REJECTED = "rejected"
APP_STATUS_CANCELLED = "cancelled"

APP_STATUSES = (
    APP_STATUS_WIZARD,
    APP_STATUS_PENDING,
    APP_STATUS_APPROVED,
    APP_STATUS_REJECTED,
    APP_STATUS_CANCELLED,
)

# inviters.review_mode
REVIEW_MODE_SELF = "self"
REVIEW_MODE_DELEGATED = "admin_delegated"
REVIEW_MODES = (REVIEW_MODE_SELF, REVIEW_MODE_DELEGATED)

# admins.role
ROLE_SUPER = "super"
ROLE_SUB = "sub"
ROLES = (ROLE_SUPER, ROLE_SUB)

# applications.reviewed_by_type
REVIEWED_BY_INVITER = "inviter"
REVIEWED_BY_ADMIN = "admin"

# material_type
MAT_BOOKING = "约课记录"
MAT_GESTURE = "上课手势"
MAT_REPORT = "出击报告"
MAT_TYPES = (MAT_BOOKING, MAT_GESTURE, MAT_REPORT)

# content_type
CT_PHOTO = "photo"
CT_TEXT = "text"
CT_TYPES = (CT_PHOTO, CT_TEXT)

# recovery_keys.status
RK_ACTIVE = "active"
RK_USED = "used"
RK_REVOKED = "revoked"
RK_RESET = "reset"
RK_STATUSES = (RK_ACTIVE, RK_USED, RK_REVOKED, RK_RESET)

# recovery_keys.cleanup_action
CLEANUP_KICK = "kick"
CLEANUP_BAN = "ban"
CLEANUP_SKIP_NOT_IN_GROUP = "skip_not_in_group"
CLEANUP_SKIP_ADMIN = "skip_admin"
CLEANUP_FAILED_NO_PERMISSION = "failed_no_permission"
CLEANUP_PENDING = "pending"
CLEANUP_ACTIONS = (
    CLEANUP_KICK,
    CLEANUP_BAN,
    CLEANUP_SKIP_NOT_IN_GROUP,
    CLEANUP_SKIP_ADMIN,
    CLEANUP_FAILED_NO_PERMISSION,
    CLEANUP_PENDING,
)

# recovery_keys.cleanup_old_account_status
CLEANUP_STATUS_NORMAL = "normal"
CLEANUP_STATUS_DEACTIVATED = "deactivated"
CLEANUP_STATUS_UNKNOWN = "unknown"

# attack_report_forwards.status
ARF_SENT = "sent"
ARF_FAILED = "failed"
ARF_SKIPPED_NO_REPORT = "skipped_no_report"
ARF_SKIPPED_NO_CHANNEL = "skipped_no_channel"
ARF_STATUSES = (ARF_SENT, ARF_FAILED, ARF_SKIPPED_NO_REPORT, ARF_SKIPPED_NO_CHANNEL)

# settings keys
SK_LOG_CHANNEL_ID = "log_channel_id"
SK_ATTACK_REPORT_CHANNEL_ID = "attack_report_channel_id"
SK_INVITE_LINK_TTL_HOURS = "invite_link_ttl_hours"
