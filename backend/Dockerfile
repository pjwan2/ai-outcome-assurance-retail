FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runs as an unprivileged user, not root — the app only ever needs to bind a
# non-privileged port (8000) and write to /data, neither of which needs root.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /data && chown -R app:app /app /data
USER app

ENV DATABASE_URL=sqlite:////data/ai_outcome_assurance.db
ENV HOST=0.0.0.0
VOLUME ["/data"]

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic upgrade head && python run_server.py"]
