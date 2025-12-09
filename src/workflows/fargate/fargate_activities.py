"""Fargate sandbox activities for running coding agents in isolated tasks.

These activities demonstrate two communication patterns between Temporal and
Fargate tasks used as sandboxes for coding agents:

1. Long-running activity that *stays open* and polls the sandbox, using
   heartbeats so Temporal can detect dead sandboxes and retry.
2. Fire-and-forget activity that launches a sandbox quickly and returns a
   task identifier so the Fargate task can signal the Workflow on completion.

The implementations deliberately simulate Fargate behavior instead of calling
AWS APIs directly. In a real system, these activities would:

- Call AWS ECS/Fargate to start tasks (for example, `RunTask`).
- Poll task status (for example, `DescribeTasks`) while heartbeating.
- Use EFS or S3 for filesystem isolation and persistence across runs.
"""

from __future__ import annotations

import asyncio
import uuid
from enum import Enum

from pydantic import BaseModel
from temporalio import activity


class FargateSandboxConfig(BaseModel):
    """Configuration for launching a Fargate-based sandbox."""

    cluster: str
    """Name or ARN of the ECS cluster."""

    task_definition: str
    """Name or ARN of the ECS task definition used for the sandbox."""

    subnets: list[str]
    """Subnets used for sandbox networking."""

    assign_public_ip: bool = False
    """Whether to assign a public IP to the sandbox task."""


class SandboxStatus(str, Enum):
    """High-level status for a sandbox task."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LongRunningSandboxInput(BaseModel):
    """Input model for a long-running sandbox activity that polls for result.

    This pattern keeps the Activity open for the lifetime of the sandbox and
    heartbeats periodically while polling whatever coordination endpoint you
    use (for example, a status API that the Fargate task updates).
    """

    config: FargateSandboxConfig
    """Fargate configuration used to launch the sandbox."""

    poll_interval_seconds: int = 30
    """How often to poll the sandbox for progress (and heartbeat)."""

    max_polls: int = 10
    """Maximum number of polls before treating the run as completed."""


class SandboxResult(BaseModel):
    """Result of a sandbox run as observed by Temporal."""

    sandbox_id: str
    """Stable identifier for the sandbox (for example, ECS task ARN)."""

    status: SandboxStatus
    """Final status of the sandbox run."""

    result_payload: str | None = None
    """Opaque result payload returned by the sandbox (for example, logs or summary)."""


class FireAndForgetSandboxInput(BaseModel):
    """Input model for a fire-and-forget sandbox activity.

    This pattern launches a Fargate task and returns immediately. The sandbox
    is responsible for signaling the Workflow when it finishes.
    """

    config: FargateSandboxConfig
    """Fargate configuration used to launch the sandbox."""


class FireAndForgetSandboxOutput(BaseModel):
    """Output model for a fire-and-forget sandbox launch."""

    sandbox_id: str
    """Identifier of the launched sandbox task."""


@activity.defn
async def start_sandbox_and_poll(input: LongRunningSandboxInput) -> SandboxResult:
    """Launch a sandbox and poll it until completion, heartbeating as we go.

    This pattern is appropriate when:

    - You want the Activity to maintain a live connection to the sandbox.
    - You need frequent progress updates.
    - You are comfortable tying up an Activity worker slot for the duration.

    For truly multi-hour runs, the `start_to_close_timeout` on the Activity
    should be set to hours, and this Activity should heartbeat often enough
    that Temporal can reliably detect when the sandbox dies and retry.
    """
    activity.logger.info(
        "Launching Fargate sandbox for long-running polling pattern: "
        "cluster=%s task_definition=%s",
        input.config.cluster,
        input.config.task_definition,
    )

    # In a real implementation this would call AWS ECS `RunTask` and return the
    # resulting task ARN. Here we simulate a stable sandbox identifier.
    sandbox_id = f"sandbox-{uuid.uuid4()}"

    # Simulate repeated polling with heartbeats so Temporal can detect failures.
    for poll_number in range(1, input.max_polls + 1):
        activity.logger.info(
            "Polling sandbox status (sandbox_id=%s poll=%d/%d)",
            sandbox_id,
            poll_number,
            input.max_polls,
        )
        # Heartbeat includes minimal contextual information so failure and retry
        # logic can reason about which sandbox was being tracked.
        activity.heartbeat(
            {
                "sandbox_id": sandbox_id,
                "poll_number": poll_number,
            }
        )

        # For tests you can configure `poll_interval_seconds=0` so this loop
        # completes immediately. In production this would be a real sleep between
        # calls to a status API or log endpoint.
        if input.poll_interval_seconds > 0:
            await asyncio.sleep(input.poll_interval_seconds)

    activity.logger.info("Completed polling for sandbox %s", sandbox_id)

    return SandboxResult(
        sandbox_id=sandbox_id,
        status=SandboxStatus.COMPLETED,
        result_payload="Simulated sandbox result after polling.",
    )


@activity.defn
async def start_sandbox_fire_and_forget(
    input: FireAndForgetSandboxInput,
) -> FireAndForgetSandboxOutput:
    """Launch a sandbox and return immediately without polling.

    This pattern is appropriate when:

    - You do not need per-minute visibility into sandbox progress.
    - The sandbox can call back into Temporal (for example, via a signal).
    - You want Activities to remain short-lived and inexpensive.

    The launched Fargate task is expected to signal the Workflow when it
    completes. Temporal remains the source of truth for orchestration, while
    the Fargate task is the isolated compute sandbox.
    """
    activity.logger.info(
        "Launching Fargate sandbox for fire-and-forget pattern: "
        "cluster=%s task_definition=%s",
        input.config.cluster,
        input.config.task_definition,
    )

    # In a real implementation this would call AWS ECS `RunTask` and return the
    # task ARN. Here we simulate a sandbox identifier.
    sandbox_id = f"sandbox-{uuid.uuid4()}"

    return FireAndForgetSandboxOutput(sandbox_id=sandbox_id)

