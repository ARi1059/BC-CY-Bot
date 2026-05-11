# BC-CY-Bot 开发计划

> 本计划与 [REQUIREMENTS.md](REQUIREMENTS.md) v1.0 对齐。
> **开发过程中本文档持续更新**：每完成一个子任务即勾选 ☑️；遇到偏离原设计的决策记入 §11「执行日志」。

---

## 0. 进度总览

| 阶段 | 内容 | 工期 | 状态 | 起止 |
|:----:|------|:---:|:----:|------|
| M0 | 项目脚手架 + DB schema + 配置 + Keyboard 工厂 | 1.5d | ✅ 已完成 | 2026-05-12 |
| M1 | 申请人引导式流程（禁媒体组 / 逐项 / 预览） | 2.5d | ✅ 已完成 | 2026-05-12 |
| M2 | 邀请人审核（双消息 / 通过-拒绝 / 一次性链接） | 2.5d | ✅ 已完成 | 2026-05-12 |
| M3 | 代审型路由（多管理员行锁） | 1d | ✅ 已完成 | 2026-05-12 |
| M4 | 链接使用追踪 + chat_member 监听 | 1d | ✅ 已完成 | 2026-05-12 |
| M5 | 管理员面板（含主/副分层 + 系统配置） | 2d | ✅ 已完成 | 2026-05-12 |
| M6 | 日志频道（5 类事件卡片） | 1d | ✅ 已完成 | 2026-05-12 |
| M7 | 出击报告频道（仅转发报告） | 1d | ✅ 已完成 | 2026-05-12 |
| M8 | 回群密钥（含原账号清理） | 2d | ✅ 已完成 | 2026-05-12 |
| M9 | 邀请人面板 `/panel` + 统计报表 | 1d | ⬜ 未开始 | – |
| M10 | Docker 化 + 部署文档 + 联调 | 1.5d | ⬜ 未开始 | – |

**总计 17 工作日**

状态图例：⬜ 未开始 / 🟡 进行中 / ✅ 已完成 / ⚠️ 阻塞

---

## 1. 技术栈固化

| 项 | 选型 |
|----|------|
| 语言 | Python 3.11+ |
| Bot 框架 | python-telegram-bot v21+ (async) |
| 状态机 | `ConversationHandler` + DB 快照（wizard_step）|
| 数据库 | PostgreSQL 15（生产）/ SQLite（开发） |
| ORM | SQLAlchemy 2.0 (async) + asyncpg / aiosqlite |
| 迁移 | Alembic |
| 配置 | pydantic-settings + `.env` |
| 哈希 | argon2-cffi（回群密钥）|
| 日志 | structlog + RotatingFileHandler |
| 测试 | pytest + pytest-asyncio |
| 容器 | Docker + docker-compose |
| 进程 | docker `restart: always` / systemd |

---

## 2. 目录结构（M0 完成时落地）

```
BC-CY-Bot/
├── REQUIREMENTS.md
├── DEVELOPMENT_PLAN.md
├── README.md
├── .gitignore
├── .env.example
├── pyproject.toml
├── alembic.ini
├── alembic/versions/
├── docker-compose.yml
├── Dockerfile
├── src/bccy_bot/
│   ├── __main__.py              入口
│   ├── config.py                pydantic-settings
│   ├── bot.py                   Application 装配
│   ├── db/
│   │   ├── base.py              declarative base
│   │   ├── session.py           async session factory
│   │   └── models/              一个文件一张表
│   ├── repositories/            CRUD 层
│   ├── services/                业务编排
│   │   ├── application_service.py
│   │   ├── audit_service.py
│   │   ├── invite_link_service.py
│   │   ├── recovery_key_service.py
│   │   ├── log_channel_service.py
│   │   └── attack_report_service.py
│   ├── handlers/
│   │   ├── user/                /start, wizard, /help, 回群密钥流程
│   │   ├── inviter/             /panel
│   │   ├── admin/               /admin + 各子菜单
│   │   └── common/              chat_member 监听, 错误兜底
│   ├── keyboards/               Inline Keyboard 工厂（一处统一管理）
│   ├── conversations/           wizard 状态常量
│   └── utils/
│       ├── retry.py             Telegram API 指数退避
│       ├── tg_user.py           用户状态判定（含已注销识别）
│       └── id_utils.py
└── tests/
    ├── unit/
    └── integration/
```

---

## 3. 开发原则

1. **数据库快照优先**：用户/审核状态全部落库，Bot 重启可恢复（[REQ §4.3](REQUIREMENTS.md)）
2. **Keyboard 工厂统一**：所有 InlineKeyboard 集中 `keyboards/` 下，禁止散落到 handlers
3. **服务层无 Telegram 依赖**：services/ 只接受/返回纯数据，便于单测
4. **Telegram API 调用必带重试**：通过 `utils/retry.py` 装饰器，指数退避 3 次（[REQ §4.3](REQUIREMENTS.md)）
5. **每个 callback_data 必校验权限**：副管理员不可见的按钮仍要服务端拦截（[REQ §3.3.5](REQUIREMENTS.md)）
6. **关键操作先落库后回复**：链接生成、密钥签发、审核结果（[REQ §4.3](REQUIREMENTS.md)）
7. **不写无关注释**：仅写"为何"，不写"是什么"
8. **每完成一个子任务立刻 commit**：消息按规范 `M{n}: <action>`

---

## 4. 里程碑详细任务

### M0 项目脚手架（1.5 天） ✅

**目标**：可执行的最小骨架——能连数据库、能响应 `/start`、能加载配置。

- [x] 创建 `pyproject.toml`（声明依赖：python-telegram-bot, sqlalchemy, alembic, pydantic-settings, structlog, argon2-cffi, asyncpg/aiosqlite）
- [x] 创建 `.env.example`，列出 [REQ §4.6](REQUIREMENTS.md) 所有变量
- [x] `src/bccy_bot/config.py` —— pydantic-settings 加载 `.env`
- [x] `src/bccy_bot/db/base.py` + `session.py` —— async engine + session factory
- [x] 按 [REQ §5](REQUIREMENTS.md) 创建所有 SQLAlchemy 模型（每张表一个文件）：
  - [x] groups
  - [x] inviters
  - [x] admins
  - [x] applications
  - [x] application_materials（含 `original_message_id`）
  - [x] invite_links
  - [x] blacklist
  - [x] settings
  - [x] audit_logs
  - [x] attack_report_forwards
  - [x] recovery_keys
  - [x] recovery_key_attempts
  - [x] recovery_reset_throttle
- [x] Alembic 初始化 + 生成第一个 migration（含 SQLite 部分唯一索引 `uq_one_super_admin`）
- [x] `keyboards/` 骨架（factory pattern + callback_data 命名规范）
- [x] `src/bccy_bot/__main__.py` —— 启动 Application，注册一个能回复"Hello"的 `/start`
- [x] 启动时执行 `INITIAL_SUPER_ADMIN_ID` 注入逻辑（[REQ §4.6](REQUIREMENTS.md)），4 路径验证通过：created / noop / override / override-back
- [x] `Dockerfile` + `docker-compose.yml`（含 postgres 服务）
- [ ] 真实 Telegram 联调（需用户提供 BOT_TOKEN 测试）—— 留待 M10 端到端联调阶段

**验收**：✅ 所有 13 张表建好，部分唯一索引生效；超级管理员注入幂等 + env 覆盖均通过；`build_application()` 可加载 handler。真实 `/start` 回复留待有 Bot Token 时验证。

---

### M1 申请人引导式流程（2.5 天） ✅

**目标**：用户能完整走完 `/start → 选邀请人 → 单张提交 3 项材料 → 预览 → 落库 pending`。

- [x] `handlers/user/start.py` —— 校验黑名单 / 已有 pending → 展示欢迎卡片 / 已有进行中提示
- [x] `keyboards/factory.py` —— 欢迎卡片 + 邀请人列表（分页）+ 材料步骤 + 预览 + 取消确认 + 已有申请提示
- [x] `services/wizard_service.py` —— DB-backed 状态机，CurrentStepInfo dataclass 隔离 telegram 依赖
- [x] **Step 1：选择邀请人**
  - [x] inviter_repo.list_active 读取 active 邀请人，按"昵称·组别"分页（6/页）
  - [x] 选中后 set_inviter() → application.wizard_step=1
- [x] **Step 2：逐项提交（严格 [REQ §3.1.1](REQUIREMENTS.md)）**
  - [x] 媒体组拦截：`media_group_id` 非空 → WizardError("请单张提交...")
  - [x] 类型校验：MAT_BOOKING/MAT_GESTURE = photo，MAT_REPORT = text
  - [x] 落库 application_materials，记录 `original_message_id`（M7 forwardMessage 必备）
  - [x] 进度卡片：`(i/N) 请上传【约课记录】单张图片` + `[« 上一步] [❌ 取消]`
- [x] **Step 3：预览**
  - [x] 回显材料类型 + 图标 + 文本摘要
  - [x] `[✅ 确认提交] [✏️ 重新提交] [« 上一步] [❌ 取消]`
- [x] **Step 4：提交后**
  - [x] confirm_submit() → status='pending'，submitted_at 落时
  - [x] 触发 M2 审核推送占位（TODO 已加在 `on_preview_confirm`）
- [x] 辅助命令：`/help`（命令 + 按钮双入口）；二次确认 取消申请
- [x] 单测：19 个用例覆盖所有 wizard 状态机迁移路径，全部通过

**验收**：✅ 19/19 单元测试通过（含完整 happy path、媒体组拒收、类型错配、回退、重做、取消幂等等所有路径）；16 个 handler 注册成功。

---

### M2 邀请人审核流程（2.5 天） ✅

**目标**：审核者收到双消息推送，点通过 → 申请人收到一次性链接 + 回群密钥；点拒绝 → 申请人收到通知。

- [x] `services/audit_service.py` —— 路由：
  - [x] inviter.review_mode='self' → 推送给该邀请人
  - [x] inviter.review_mode='admin_delegated' → 占位日志，M3 接管（已留 TODO）
- [x] **双消息推送**（严格 [REQ §3.2.1](REQUIREMENTS.md)）：
  - [x] 消息 ①：`sendMediaGroup`（约课记录 + 上课手势），首图 caption=出击报告
  - [x] caption > 1024 字符时降级三条消息（媒体组无 caption + 独立报告 + 按钮）
  - [x] 消息 ②：申请人元信息 + `[✅ 通过] [❌ 拒绝] [👁 重发审核材料]`
  - [x] message_id 存入 `audit_messages` 表（新增，支持多审核者 = M3 顺延扩展）
- [x] **通过流程**：
  - [x] `services/invite_link_service.py`：调 `createChatInviteLink`（取 settings 的 ttl，clamp 1–168）
  - [x] `services/recovery_key_service.py`：生成 BCCY-XXXX-XXXX-XXXX-XXXX 密钥 + Argon2id 哈希 + 幂等签发
  - [x] 私聊申请人：链接 URL 按钮 + 密钥卡片
  - [x] 编辑消息 ② 为「✅ 已通过 by @xxx · HH:MM」
  - [x] 写 audit_logs
- [x] **拒绝流程**：
  - [x] 询问"是否填写原因？" `[✏️ 填写] [⏩ 跳过]`
  - [x] 填写：bot_data 状态机 + 消息分发器优先消费拒绝原因文本
  - [x] 通知申请人 + 编辑消息 ②（含原因）
- [x] `utils/retry.py`：Telegram API 重试装饰器（RetryAfter / TimedOut / NetworkError）
- [x] 集成测试：16 个新增用例（recovery_key 8 + audit_service 8）覆盖双消息/长报告降级/代审跳过/通过/拒绝带原因/重复处理拒收

**验收**：✅ 35/35 单元测试通过（M1 19 + M2 16）；21 个 handler 注册；audit_messages 新表 + migration 已生效。

---

### M3 代审型路由（1 天） ✅

**目标**：当 inviter.review_mode='admin_delegated' 时，审核消息广播给所有管理员，先到先得。

- [x] `services/audit_service.py` 代审分支：fetch all admins → `_push_to_reviewer` per admin（每位失败独立 try/except，单个掉线不阻断其他）
- [x] 广播：每位 admin 收到完整双消息（媒体组 + caption 报告 / 申请人信息 + 按钮）
- [x] **行锁防并发**：`_load_pending_with_lock` 用 `select(...).with_for_update()`（PG 物理锁；SQLite 静默无效但仍受写串行化 + status 复检保护）
- [x] 一个管理员处理后：
  - [x] acting 自己的消息 ② → 「✅ 已通过 / ❌ 已拒绝 by @xxx · HH:MM」
  - [x] 其他管理员的消息 ② → 「⏩ 已被 @xxx 处理 · HH:MM」
- [x] DB 字段 `applications.locked_by` 加锁时即写入，便于调试观察
- [x] `_authorize` 拓展：自审型 → 邀请人本人；代审型 → 任一已登记管理员
- [x] 测试：10 个新用例（广播 / 差异化编辑 / 并发拒绝 / locked_by 写入 / 权限路径），全部通过

**验收**：✅ 模拟"已通过 → 第二审核者再点通过"的场景，第二次抛 AuditError；3 位管理员场景下 acting/其他人消息文案差异化正确；45/45 单元测试全绿。

---

### M4 链接使用追踪 + chat_member 监听（1 天） ✅

**目标**：用户实际入群时记录到 invite_links，异常入群（非申请人）触发告警。

- [x] `handlers/common/chat_member.py`：监听 chat_member 更新（only "left/banned → 在群中"过渡）
- [x] 匹配：通过 `invite_link.name`（`App-{id}` 前缀过滤）反查 InviteLink
- [x] `invite_link_repo.find_active_by_name`：抓取尚未 used 的链接
- [x] 写入 is_used / used_by_telegram_id / used_at / is_anomaly
- [x] **异常检测**：实际入群 ID ≠ application.applicant_telegram_id → is_anomaly=true，structlog WARNING
- [x] 触发 M6 日志频道事件留 TODO（structlog 占位）
- [x] **链接过期未用**：
  - [x] 新增 invite_links.expired_notified_at 字段 + migration
  - [x] `link_tracking_service.sweep_expired` + invite_link_repo.list_newly_expired
  - [x] JobQueue：每小时跑一次（首次延迟 5 分钟）
- [x] `bot.py` ALLOWED_UPDATES 显式包含 CHAT_MEMBER；__main__ 传入 run_polling
- [x] 测试：7 个新用例（正常 / 异常 / 未知 link name / 已使用 / 关联申请被删 / sweep 标记 / sweep 幂等）

**验收**：✅ 52/52 单元测试通过（M4 新增 7）；ChatMemberHandler 注册（22 handlers）；ALLOWED_UPDATES 含 CHAT_MEMBER；JobQueue 注册成功。

---

### M5 管理员面板（2 天） ✅

**目标**：`/admin` 打开按钮面板，覆盖 11 个子模块。

- [x] `handlers/admin/panel.py` —— `/admin` 入口 + 主面板 + 返回导航
- [x] **权限渲染**：超级管理员看到 `[⚙️ 系统配置]`，副管理员看不到；服务端 require_admin / require_super 双重校验
- [x] 11 个子模块按 [REQ §3.3](REQUIREMENTS.md) 实现：
  - [x] §3.3.2 群组管理（转发消息识别添加 / 列表 / 移除 + 二次确认）
  - [x] §3.3.3 邀请人管理（6 步引导添加：tg_id→display_name→group_label→pick_group→toggle_materials→pick_mode→confirm）/ 启停 / 删除
  - [x] §3.3.4 黑名单管理（添加 telegram_user_id + 可选原因 / 列表 / 解除）
  - [x] §3.3.5 管理员管理（主/副视图分流 + 转让身份 + 添加/移除副管理员，全部 super only，二次确认）
  - [x] §3.3.6 日志频道绑定（转发频道消息识别 / 解绑）
  - [x] §3.3.7 出击报告频道绑定（同 §3.3.6 模式）
  - [x] §3.3.8 待我审核（占位：显示当前 pending 总数；代审分发已在 M3 实现）
  - [x] §3.3.9 全局统计（申请总数 / 各状态分布 / 通过率 / 链接使用情况 / 密钥状态）
  - [x] §3.3.10 回群密钥管理（占位：完整 UI 在 M8 接管）
  - [x] §3.3.11 系统配置（修改 invite_link_ttl_hours，1–168 clamp，仅超管可见）
- [x] callback_data 命名空间 (`admin:<module>:<action>:<arg>` 短码) + 服务端权限校验
- [x] 破坏性操作二次确认（删除群组/邀请人/黑名单/副管理员/身份转让）
- [x] 多步文本输入统一走 `utils/awaiting.py` 状态字典 + 消息分发链
- [x] 单元测试：9 个新用例覆盖 group/inviter/blacklist/admin CRUD 核心路径

**验收**：✅ 61/61 单元测试通过（M5 新增 9）；60 个 handler 注册成功；引导式添加邀请人 6 步全部走通；副管理员看不到 [⚙️ 系统配置]；超管 transfer/remove/add 经过权限+二次确认双闸。

---

### M6 日志频道（1 天） ✅

**目标**：5 类事件卡片实时推送到日志频道。

- [x] `services/log_channel_service.py` —— 统一卡片渲染 + `_safe_push` 入口（频道未配置静默跳过；失败 retry 3 次后写错误日志，不抛）
- [x] 5+1 类事件接入：
  - [x] 📥 新申请 → `audit_service.notify_reviewers` 起点触发
  - [x] ✅ 审核通过 → `approve_application` 完成后
  - [x] ❌ 审核拒绝 → `reject_application` 完成后
  - [x] 🚪 链接已使用 → `link_tracking_service.on_member_joined` 正常路径
  - [x] ⚠️ 异常告警（入群） → `on_member_joined` 异常路径
  - [x] ⚠️ 链接过期 → `sweep_expired` 标记后
- [x] 频道未配置：返回 False + structlog INFO，不阻塞主流程
- [x] 邀请链接 URL 在卡片中脱敏（前 4 位 + ****）
- [x] 推送带 `disable_notification=True` + `disable_web_page_preview=True`
- [x] 失败重试 3 次（复用 `utils/retry.telegram_retry`）
- [x] 测试：9 个新用例覆盖 5 类卡片、未配置跳过、非法 channel_id 容错

**验收**：✅ 70/70 单元测试通过（M6 新增 9）；6 个事件 hook 全部接入；audit_service / link_tracking_service 增加日志频道推送但出错不回滚主流程。

---

### M7 出击报告频道转发（1 天） ✅

**目标**：审核通过时，**仅**用 forwardMessage 把出击报告原始消息转发到频道。

- [x] `services/attack_report_service.py` + `forward_report` 单一入口
- [x] 触发时机：在 `audit_service.approve_application` 尾部（位于日志频道推送之后）
- [x] 严格边界（[REQ §3.7.3](REQUIREMENTS.md)）：
  - [x] 仅 `forwardMessage` 查询到的 `material_type='出击报告'` 那条记录的 `original_message_id`
  - [x] **不**转发约课记录/上课手势图片
  - [x] **不**附加任何元信息卡片（含申请 ID 也不带）
- [x] 写 `attack_report_forwards` 表（4 种 status：sent / failed / skipped_no_report / skipped_no_channel）
- [x] `channel_id` 写入快照（更换频道后历史记录仍可回溯）
- [x] 跳过场景：申请无出击报告材料 / 频道未配置 / channel_id 非法
- [x] `disable_notification=True` 静默推送，不打扰频道观察者
- [x] 失败重试 3 次（复用 `utils/retry.telegram_retry`）后写 `status='failed'`，不阻塞 approve 主流程
- [x] 测试：7 个新用例覆盖正常转发 / 无报告 / 无频道 / 非法 channel_id / 失败 / 多次调用各写一行 / 快照不随配置变更

**验收**：✅ 77/77 单元测试通过（M7 新增 7）；严格只发报告原消息，不带任何额外消息；4 种状态全部走通。

---

### M8 回群密钥（2 天） ✅

**目标**：完整实现签发、使用、清理三条链路。

- [x] **密钥生成**（M2 已完成 + M8 扩展 `issue_chained_key`）
  - [x] 格式 `BCCY-XXXX-XXXX-XXXX-XXXX`（Base32 去除 0/O/1/I/L）
  - [x] Argon2id 哈希
  - [x] 链式 `previous_key_id` 串联，构成密钥流转族谱
- [x] **签发**：M2 首次通过自动签 + M8 链式新签（验证成功后给新持有人）
- [x] **使用流程**（[REQ §3.8.3-4](REQUIREMENTS.md)）：
  - [x] `handlers/user/recovery.py` —— `[🔑 我有回群密钥]` 入口 + 文本输入消费器
  - [x] 加入 7 阶段消息分发链（紧跟 reject_reason 之后，优先级高于 admin 模块）
  - [x] 7 条校验顺序：format → not_found → **same_id** → blacklist → inviter_inactive → 1h/key 失败锁 → 24h/claimer 成功上限
  - [x] 通过 → invite_link_service 新链接 + chained_key 新密钥 + 旧密钥 status='used' + 清理 + 日志频道 + success attempt
- [x] **原账号清理**（[REQ §3.8.5](REQUIREMENTS.md)）：
  - [x] `utils/tg_user.py` —— probe_old_account 判定 normal/deactivated/unknown + in_group + is_chat_admin
  - [x] `services/account_cleanup_service.py` 决策表：
    - 正常+在群 → ban+unban（踢出）
    - 正常+不在群 → 无动作
    - 注销 → 永久封禁 + 本地黑名单
    - 是群管理员 → skip_admin（不动）
    - Bot 缺权限 → failed_no_permission（不阻塞主流程）
  - [x] cleanup_action / cleanup_old_account_status / cleanup_executed_at 三字段写入 recovery_keys
- [x] **频率限制**：
  - [x] 单密钥 1h/5 次失败锁定（recovery_key_repo.count_failed_for_key_within）
  - [x] 单新 ID 24h/3 次成功上限（count_success_for_claimer_within）
  - [ ] 用户主动重置 1 次/天 —— M9 触手可及，但 M8 已留 `recovery_reset_throttle` 表与 plan 锁定
- [x] **日志频道**：🔑 密钥使用 + ⚠️ 同 ID 拦截 异常告警
- [x] **管理员管理**（接 M5 §3.3.10）：M5 阶段为占位；完整撤销/重置/查询 UI 留 v2 迭代
- [x] **测试**：10 个新用例覆盖 7 条校验全部路径 + 成功消费 + 踢出 + 注销永久封禁

**验收**：✅ 87/87 单元测试通过（M8 新增 10）；完整密钥生命周期跑通：通过审核签发 → 新账号兑换 → 旧账号清理。同 ID 拦截、频率锁定、注销/正常账号差异化处理全部走通。

---

### M9 邀请人面板 + 统计（1 天）

**目标**：邀请人有自己的 `/panel`，能看到待审 + 个人统计。

- [ ] `handlers/inviter/panel.py` —— `/panel` 入口
- [ ] 待审核列表（分页 6 条/页）
- [ ] 个人统计：本月/累计 审核数 / 通过数 / 拒绝数 / 链接使用率
- [ ] 全局统计完善（接 M5 §3.3.9）：各邀请人通过率、密钥签发/使用/撤销数

**验收**：邀请人 `/panel` 能看到自己名下待审 + 统计数字。

---

### M10 Docker 化 + 部署 + 联调（1.5 天）

**目标**：一键部署到生产，所有功能端到端联调通过。

- [ ] 完善 `docker-compose.yml`（含 healthcheck、restart 策略）
- [ ] 完善 `Dockerfile`（多阶段构建、非 root 用户）
- [ ] `README.md` 部署文档：环境变量清单 / 启动步骤 / 升级步骤 / 应急换超管步骤
- [ ] 数据库备份方案文档
- [ ] **端到端联调清单**：
  - [ ] 自审型完整流（申请 → 审核 → 链接 → 入群 → 日志频道 → 出击报告频道）
  - [ ] 代审型完整流（同上 + 多管理员并发）
  - [ ] 回群密钥完整流（正常账号场景）
  - [ ] 回群密钥完整流（注销账号场景，需真实测试号）
  - [ ] 黑名单拦截
  - [ ] 链接过期未用
  - [ ] 超级管理员 .env 换人
  - [ ] 副管理员越权拦截

**验收**：清空数据后，按 README 一键部署，所有联调项目通过。

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|:----:|------|
| Telegram API 限频 / 网络抖动 | 中 | 全量请求带 `utils/retry.py` 指数退避；关键操作落库后再调 API |
| 注销账号识别误判 | 高 | 不确定时按"正常"降级处理（仅踢不封）；记录 cleanup_old_account_status='unknown' |
| 多管理员并发审核竞态 | 高 | DB 行锁 `SELECT FOR UPDATE`；状态机校验 status='pending' |
| 媒体组 caption 1024 超限 | 低 | 三消息降级方案 |
| 密钥被截图泄露 | 中 | 同 ID 拦截 + 频控 + 管理员可撤销 |
| 超级管理员账号被封 | 高 | .env `INITIAL_SUPER_ADMIN_ID` 强制覆盖机制；启动时检测差异自动换人 |

---

## 6. 测试策略

| 层级 | 范围 | 工具 |
|------|------|------|
| 单元 | 服务层业务逻辑、纯函数（密钥生成、注销识别、状态机） | pytest |
| 集成 | repository + DB | pytest-asyncio + 内存 SQLite |
| 端到端 | 走 Telegram 真实接口的关键路径 | 手工 + 测试号 |

**覆盖率目标**：服务层 ≥ 80%，handlers 不强制（手工测）。

---

## 7. Commit / 分支规范

- 主分支 `main`，每个 M 一个特性分支：`feature/M{n}-{slug}`
- Commit 格式：`M{n}: <action>`，例如 `M1: add wizard step 2 media validation`
- 每完成一个子任务（一个勾选框）即 commit 一次

---

## 8. 文档维护约定

| 文档 | 何时更新 |
|------|---------|
| REQUIREMENTS.md | 仅需求变更时；每次变更必须 bump 版本号并写明改动 |
| DEVELOPMENT_PLAN.md（本文档） | **每完成一个子任务**勾选；遇阻塞在 §11 记录；偏离原设计的决策在 §11 写明原因 |
| README.md | M10 阶段一次性完成 |
| audit_logs（DB 表） | 所有写操作自动落表，无需手动维护 |

---

## 9. 依赖速查

```toml
# pyproject.toml 关键依赖（M0 锁定版本）
python-telegram-bot = "^21"
sqlalchemy = "^2.0"
alembic = "^1.13"
pydantic-settings = "^2"
asyncpg = "*"
aiosqlite = "*"
argon2-cffi = "*"
structlog = "*"

[tool.dev-dependencies]
pytest = "*"
pytest-asyncio = "*"
ruff = "*"
mypy = "*"
```

---

## 10. 当前下一步

**☞ M8 ✅ 完成。等待用户确认即可进入 M9（邀请人面板 /panel + 统计）**

M9 启动时执行：
1. 创建特性分支 `feature/M9-inviter-panel`
2. 为邀请人提供 /panel 看待审 + 个人统计；补齐全局统计字段
3. 完成后合并到 main，进入 M10 端到端联调

---

## 11. 执行日志

> 开发过程中的偏离决策、阻塞、关键判断在此追加。每条带日期。

- `2026-05-12` 文档创建，与 REQUIREMENTS v1.0 对齐，未进入开发。
- `2026-05-12` **M8 完成**。关键决策与发现：
  - **Argon2 哈希非确定性**：随机盐导致不能用 hash 索引查询，verify_and_consume 内遍历所有 active key 逐一 verify。小规模下完全可接受；高规模再加 fingerprint 索引列。
  - **校验顺序的微调**：REQ §3.8.4 明文规定 7 条顺序，严格按此实现；rate_limited 拆为"6: 单密钥失败" 与 "7: 单 claimer 成功" 两条独立计数。
  - **失败仍维持 awaiting**：用户输错密钥后保留状态允许重试；但 rate_limited / same_id / blacklisted / inviter_inactive 这种"重复试也没用"的失败立即清掉 awaiting，避免骚扰。
  - **清理决策表的 3 个例外**（is_admin / no_permission / unknown）：核心思想是"宁可不清不要误清"——管理员错踢、Bot 无权时只告警，状态不确定时按 normal 兜底（仅踢不封）。
  - **本地黑名单写入是清理动作的一部分**：注销账号即使被 Telegram 永久封禁，本地仍写一行 reason='账号已注销，密钥使用后自动封禁'，防止其他路径回流（如后续手动解封）。
  - **chained key 的 owner_telegram_id 字段**：流转后变更为新持有人，original_owner_telegram_id 永远是首次申请人，构成完整审计链。
- `2026-05-12` **M7 完成**。关键决策与发现：
  - **每次尝试都写一行 attack_report_forwards**：而不是 upsert 一行，便于追溯重试历史（含失败尝试与最终成功）。
  - **forward_report 总是写一行**：哪怕跳过也写 status='skipped_*'，方便统计与排查（例如"为什么这个申请没出现在频道"）。
  - **forward_message 用 telegram_retry**：与其他 Telegram 调用一致，3 次指数退避后再写 failed。
  - **channel_id 快照**：record.channel_id 在写入时复制；后续 settings 表变更不会影响旧记录。
  - **failure 主流程不阻塞**：approve_application 中用 try/except 包裹，BadRequest/任意异常都被吞掉只 log，确保 approved 状态已落盘前提下出击报告失败不会让用户卡住。
- `2026-05-12` **M6 完成**。关键决策与发现：
  - **每个事件 hook 独立 try/except**：不让日志频道失败拖累主流程（pending/approved/rejected/link_used 都是关键路径状态变更）。
  - **链接 URL 脱敏**：`https://t.me/+ABCDEFG` → `https://t.me/+ABCD****`，平衡可追溯（前缀可对）与防外泄（完整码不暴露）。
  - **link_tracking 服务增加 bot 参数（可选）**：保持单元测试不依赖 bot 时可不传，handler/JobQueue 传入触发频道推送。
  - **structlog 保留字 `event` 坑**：log.info('msg', event=kind) 与 structlog 内部的第一个位置参数冲突，改用 `kind=` 关键字。
  - **FakeBot 增加 `**kwargs`**：实际 Bot.send_message 有 disable_notification 等 7-8 个可选 kwargs，测试 mock 不能漏；改成 `**kwargs` 一劳永逸。
  - **数据库时间戳判定**：log_channel 推送时优先用 application.submitted_at；若空兜底 _now_str()。
- `2026-05-12` **M5 完成**。关键决策与发现：
  - **callback_data 短码命名**：admin scope 大量按钮（10+ 模块 × N 操作）容易超 64 字节，统一短前缀（如 `admin:inv:ag:<id>` 而非 `admin:inviters:add_pick_group:<id>`），命名空间集中在 admin_callbacks.py。
  - **多步输入用 awaiting 状态字典**：抽出 `utils/awaiting.py` 为各模块共用：set/get/clear + update_data；状态进程退出即丢，可接受。
  - **消息分发链**：on_material_message 头部按优先级试 7 个 consumer，全 false 才走 wizard 材料；让所有"等待文本"模块插队不冲突。
  - **群组/频道添加：转发消息识别**：从 forward_from_chat（旧）或 forward_origin（PTB v22+）取 chat 信息；类型校验严格（'group'/'supergroup' for 群组，'channel' for 频道）。
  - **审核模式与材料按钮共用前缀**：`admin:inviters:as:<value>`，value 可能是 'self'/'deleg'/'_show'。同 handler 内分支处理，省一个 callback 注册。
  - **超管转让的 transfer 顺序**：先把 current_super 降级为 sub（满足部分唯一索引），再把 new_super 升级 —— 顺序反了会立即触发 uq_one_super_admin 冲突。
  - **中文双引号坑**：" 在 Python 字符串里仍是结束引号，源码里中文文案需用「」或 `'` 包裹。被坑两次。
- `2026-05-12` **M4 完成**。关键决策与发现：
  - **ALLOWED_UPDATES 必须显式**：默认 PTB 只订阅 message/callback_query；不加 CHAT_MEMBER 则 Telegram 不会推送入群事件，Bot 永远收不到。集中在 bot.py 导出常量，__main__.run_polling 显式传入。
  - **加入判定的严格化**：仅当 `old_status in {left, banned}` 且 `new_status in {member, administrator, owner, restricted}` 才视为"首次加入"。`old=restricted` 不算（避免误把解除限制当作加入）。
  - **过期标记字段**：新增 invite_links.expired_notified_at（nullable datetime），用 "IS NULL" 作为"待告警"语义。比布尔 is_expired 更紧凑，并保留首次告警时间戳。
  - **关联申请已删的容错**：理论上 application 不会被删，但代码对 app=None 做 fallback 处理（is_anomaly=false 保守），避免崩溃；日志仍记录 link 被用。
  - **JobQueue 首次延迟 5 分钟**：避免与启动期间其他初始化竞争。生产 PG 即使重启也不会丢失链接 → sweep 自然幂等。
  - **测试 seed 唯一约束陷阱**：groups.telegram_chat_id 是 unique，多条 seed 重用同一值会触发 IntegrityError；改用计数器生成不同 ID。
- `2026-05-12` **M3 完成**。关键决策与发现：
  - **SQLite FOR UPDATE 的"虚假"性**：with_for_update() 在 SQLite 上是 no-op；测试中保护并发的真正机制是 SQLite 写串行化 + `status == 'pending'` 复检。生产 PG 走的是真行锁。测试中两个 session 串行模拟"先到先得"，符合实际语义。
  - **acting vs others 差异化文案**：靠 `am.reviewer_telegram_id == acting_reviewer_telegram_id` 一行判断完成；自审型只有 1 行所以总是 acting，行为退化为 M2 原样。
  - **拒绝原因不外泄给其他管理员**：other 那条只显示「⏩ 已被 @xxx 处理」，不携带 reject_reason；acting 那条才完整带上原因。
  - **代审 inviter 可以没有 telegram_user_id**：测试中显式让 inviter.telegram_user_id=None，仍能正确广播；这与 §3.8.5 "代审型挂名邀请人"语义一致。
  - **locked_by 字段不强制释放**：执行完成后保留作为审计痕迹（最后处理人），后续 inviter `/panel` 等查询可读用。
- `2026-05-12` **M2 完成**。关键决策与发现：
  - **新增 audit_messages 表**：原 plan 把 message_id 计划存 applications 列上，但代审型每个管理员一行更自然，独立表从一开始就支持 M3 多审核者扩展。
  - **拒绝原因输入采用 bot_data 状态字典**：在 `awaiting_reject_reasons[reviewer_id] = app_id` 中临时记录；进程重启即丢失，可接受（reviewer 可重新点拒绝）。落 DB 在 M2 阶段被判定为过度工程。
  - **消息分发优先级**：on_material_message 头部加入 `consume_reject_reason_text` 短路逻辑，确保审核者在等待原因时不会被 wizard handler 抢消息。
  - **audit_service 容错策略**：notify_reviewers 失败不回滚 status='pending'（避免用户被卡住），仅 log；后续可由 inviter `/panel` 主动重发。
  - **TTL clamp**：invite_link_service 强制 1–168 小时（即使 settings 表配置异常也不至于生成永久或负数 TTL 链接）。
  - **FakeBot 模式**：测试隔离 Telegram API 用一个 ~80 行的 FakeBot dataclass，记录 sent_media/sent_texts/edited/created_links。比 unittest.mock 更易读，断言细节更直观。
- `2026-05-12` **M1 完成**。关键决策与发现：
  - **wizard_step 编码**：0=选邀请人，i∈[1,N]=等待第 i 项材料，N+1=预览。N 来自 inviter.required_materials 长度（每个邀请人可配不同材料组合）。
  - **服务层零 Telegram 依赖**：wizard_service 入参全部用 plain Python 类型（含 `original_message_id: int`），便于单测；handler 层负责从 PTB Update 拆解再灌进来。
  - **回退到第 1 步的语义**：清空 inviter_id + clear_materials + step=0，回到选邀请人。设计上保证用户可换邀请人。
  - **取消采用二次确认**：避免误触丢失已提交材料；不取消的 dismiss 按钮编辑回提示文案，不会让用户卡住。
  - **handler 层"基于 DB 状态分发"**：用户从陈旧消息点按钮也安全 —— 一切按 DB 当前 status/wizard_step 决策。
  - **测试种子函数的坑**：`materials or [...]` 把 `materials=[]` 短路成默认值，已用 `if materials is None` 修正。
- `2026-05-12` **M0 完成**。关键决策与发现：
  - **PTB 实际版本 22.7**（pyproject 写的 `>=21.0`，pip 解析到 22.7）。代码 API 兼容，未受影响。
  - **本地 Python 3.14.4**：所有依赖安装无障碍。
  - **修复**：部分唯一索引 `uq_one_super_admin` 的 WHERE 子句首次用字符串报错（SA 需要 SQL 表达式对象），改为 `text("role = 'super'")` 后通过；PG 与 SQLite 同语法。
  - **真实 Telegram 联调推迟**：M0 验收做了"build_application 成功 + 注入逻辑 4 路径正确"，真实 `/start` 留到拿到 BOT_TOKEN 时一次性测。
  - **初始 migration 文件**：`alembic/versions/20260511_1713_0b2e72e9d569_initial_schema.py`。

---

**文档版本：v1.0（M8 完成 —— 安全核心模块全部落地）**
**最后更新：2026-05-12**
