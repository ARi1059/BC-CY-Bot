FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN pip install -e . --no-deps

RUN groupadd -r bccy && useradd -r -g bccy bccy && chown -R bccy:bccy /app
USER bccy

CMD ["python", "-m", "bccy_bot"]
