"""Entry point code for a Fargate sandbox task.

This module represents the *code that runs inside the Fargate task
definition* for the Fargate sandbox workflow. A typical container
command would look like:

    python -m src.workflows.fargate.fargate_task

The task performs three high-level responsibilities:

1. Run the coding agent (simulated here with a placeholder function).
2. Connect to Temporal as a client.
3. Signal the ``FargateSandboxWorkflow`` that the sandbox has finished.

In a real deployment, the ECS task definition would inject the Workflow
identity and Temporal connection information via environment variables.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Final

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from src.workflows.fargate.fargate_activities import SandboxStatus

logger = logging.getLogger(__name__)

# Environment variable contracts for the Fargate task.
TEMPORAL_TARGET_ENV: Final[str] = "TEMPORAL_TARGET_HOSTPORT"
TEMPORAL_NAMESPACE_ENV: Final[str] = "TEMPORAL_NAMESPACE"
TEMPORAL_WORKFLOW_ID_ENV: Final[str] = "TEMPORAL_WORKFLOW_ID"
TEMPORAL_WORKFLOW_RUN_ID_ENV: Final[str] = "TEMPORAL_WORKFLOW_RUN_ID"
FARGATE_SANDBOX_ID_ENV: Final[str] = "FARGATE_SANDBOX_ID"

# Defaults suitable for local development with a Temporal dev server.
DEFAULT_TEMPORAL_TARGET: Final[str] = "localhost:7233"
DEFAULT_TEMPORAL_NAMESPACE: Final[str] = "default"

# Name of the signal defined on ``FargateSandboxWorkflow`` that the sandbox
# task will invoke upon completion.
SANDBOX_COMPLETED_SIGNAL_NAME: Final[str] = "sandbox_completed"


def _require_env(name: str) -> str:
    """Return the required environment variable or raise an error."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


async def run_coding_agent(sandbox_id: str) -> str:
    """Simulate running a coding agent inside the sandbox.

    In a production system this function would:

    - Initialize any model or tool backends used by the agent.
    - Receive a task description and context (for example, via SQS, HTTP, or
      a mounted filesystem).
    - Execute the coding task, writing results to an isolated filesystem or
      object store.

    For this template, the implementation simply logs start/finish messages
    and returns a small summary string.
    """
    logger.info("Starting coding agent in sandbox %s", sandbox_id)

    # Placeholder for real work. In practice this could be minutes or hours
    # of execution depending on the agent workload.
    await asyncio.sleep(0)

    result_summary = f"Coding agent completed successfully in sandbox {sandbox_id}"
    logger.info("Finished coding agent in sandbox %s", sandbox_id)
    return result_summary


async def main() -> None:
    """Run the sandbox task and signal the Temporal workflow."""
    temporal_target = os.getenv(TEMPORAL_TARGET_ENV, DEFAULT_TEMPORAL_TARGET)
    temporal_namespace = os.getenv(TEMPORAL_NAMESPACE_ENV, DEFAULT_TEMPORAL_NAMESPACE)
    workflow_id = _require_env(TEMPORAL_WORKFLOW_ID_ENV)
    workflow_run_id = os.getenv(TEMPORAL_WORKFLOW_RUN_ID_ENV) or None
    sandbox_id = _require_env(FARGATE_SANDBOX_ID_ENV)

    logger.info(
        "Fargate sandbox starting with workflow_id=%s run_id=%s sandbox_id=%s "
        "target=%s namespace=%s",
        workflow_id,
        workflow_run_id,
        sandbox_id,
        temporal_target,
        temporal_namespace,
    )

    # Run the coding agent workload inside the sandbox.
    result_payload = await run_coding_agent(sandbox_id)

    # Connect to Temporal and signal the Workflow that this sandbox has
    # completed. Temporal remains the source of truth for orchestration;
    # this task only reports its final status.
    client = await Client.connect(
        temporal_target,
        namespace=temporal_namespace,
        data_converter=pydantic_data_converter,
    )
    handle = client.get_workflow_handle(
        workflow_id=workflow_id,
        run_id=workflow_run_id,
    )

    logger.info(
        "Signaling workflow %s (run_id=%s) that sandbox %s completed",
        workflow_id,
        workflow_run_id,
        sandbox_id,
    )
    await handle.signal(
        SANDBOX_COMPLETED_SIGNAL_NAME,
        args=[sandbox_id, SandboxStatus.COMPLETED, result_payload],
    )

    logger.info(
        "Successfully signaled completion for sandbox %s to workflow %s",
        sandbox_id,
        workflow_id,
    )


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

