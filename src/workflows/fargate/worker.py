"""Worker for the Fargate sandbox Workflow."""

from __future__ import annotations
from src.workflows.fargate.config import TEMPORAL_NAMESPACE, TEMPORAL_URL, TEMPORAL_API_KEY
import asyncio
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from src.workflows.fargate.fargate_activities import (
    start_sandbox_and_poll,
    start_sandbox_fire_and_forget,
)
from src.workflows.fargate.fargate_workflow import FargateSandboxWorkflow


async def main() -> None:
    """Connects to the client, starts a worker, and runs the Fargate workflow."""
    client = await Client.connect(TEMPORAL_URL, namespace=TEMPORAL_NAMESPACE, api_key=TEMPORAL_API_KEY, data_converter=pydantic_data_converter, tls=True)
    task_queue = "fargate-sandbox-task-queue"
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[FargateSandboxWorkflow],
        activities=[start_sandbox_and_poll, start_sandbox_fire_and_forget],
        activity_executor=ThreadPoolExecutor(5),
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

