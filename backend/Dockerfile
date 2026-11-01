# Python 3.11.15 / Alpine 3.24.2, reviewed 2026-09-18.
FROM python:3.11-alpine@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONPATH=/app

WORKDIR /app

# Dependencies use binary wheels, including psycopg2-binary. Keep available
# system patches while leaving compilers and PostgreSQL headers out of runtime.
RUN apk upgrade --no-cache

COPY requirements.txt requirements.lock /app/
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /app/requirements.lock \
  && pip check \
  && pip uninstall --yes pip

COPY . /app

EXPOSE 9247

CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host '' --port ${PORT:-9247}"]
