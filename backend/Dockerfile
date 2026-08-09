FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATABASE_URL=sqlite:////data/ai_outcome_assurance.db
ENV HOST=0.0.0.0
VOLUME ["/data"]

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic upgrade head && python run_server.py"]
