FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 项目源 + 元信息：hatchling 后端打包 wheel 时需要 src/，必须一起 COPY
COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

# 在独立 venv 中安装，方便 stage 2 整体复制
RUN python -m venv /venv && \
    /venv/bin/pip install --upgrade pip && \
    /venv/bin/pip install .


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:${PATH}" \
    TZ=Asia/Shanghai

WORKDIR /app

COPY --from=builder /venv /venv
COPY --from=builder /app/alembic.ini ./
COPY --from=builder /app/alembic ./alembic
COPY --from=builder /app/src ./src

# 非 root 运行，减少容器逃逸面
RUN groupadd -r bccy && useradd -r -g bccy bccy && chown -R bccy:bccy /app /venv
USER bccy

CMD ["python", "-m", "bccy_bot"]
