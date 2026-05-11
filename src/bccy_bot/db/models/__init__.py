"""所有 ORM 模型集中 re-export，方便 Alembic 自动发现。"""

from bccy_bot.db.models.admin import Admin
from bccy_bot.db.models.application import Application
from bccy_bot.db.models.application_material import ApplicationMaterial
from bccy_bot.db.models.attack_report_forward import AttackReportForward
from bccy_bot.db.models.audit_log import AuditLog
from bccy_bot.db.models.blacklist import Blacklist
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.db.models.recovery_key import RecoveryKey
from bccy_bot.db.models.recovery_key_attempt import RecoveryKeyAttempt
from bccy_bot.db.models.recovery_reset_throttle import RecoveryResetThrottle
from bccy_bot.db.models.settings import Setting

__all__ = [
    "Admin",
    "Application",
    "ApplicationMaterial",
    "AttackReportForward",
    "AuditLog",
    "Blacklist",
    "Group",
    "InviteLink",
    "Inviter",
    "RecoveryKey",
    "RecoveryKeyAttempt",
    "RecoveryResetThrottle",
    "Setting",
]
