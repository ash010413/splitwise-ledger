FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements-cloud.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-cloud.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps '.[cloud]' && useradd --uid 10001 --create-home minto
USER 10001
CMD ["sh", "-c", "exec uvicorn splitwise_ledger.api:create_app --factory --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --no-access-log"]
