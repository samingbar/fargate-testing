FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

ENV PYTHONPATH=/app \
    TEMPORAL_TARGET_HOSTPORT=us-east-2.aws.api.temporal.io:7233 \
    TEMPORAL_NAMESPACE=fargate-tasks-demo.a2dd6

CMD ["python", "-m", "src.workflows.fargate.example_fargate_task.fargate_task"]
