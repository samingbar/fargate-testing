"""Workflow for orchestrating coding agents in Fargate sandboxes.

This Workflow demonstrates two complementary patterns for using Temporal to
orchestrate Fargate tasks as *isolated sandboxes* for coding agents:

1. **Polling pattern**: a long-running Activity launches a sandbox task and
   stays open, polling a coordination endpoint and heartbeating so Temporal
   can detect dead sandboxes and retry.
2. **Signal pattern**: a short Activity fire-and-forgets the sandbox and the
   Fargate task signals the Workflow when it completes.

Temporal itself never runs inside the Fargate task. Activities simply call
external services (for example, AWS ECS/Fargate) and Temporal tracks their
completion and retries. Memory isolation between Workflow and Activity code
is already guaranteed by Temporal's execution model; filesystem isolation is
handled by how you configure the Fargate task (for example, EFS or S3).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from multiprocessing.dummy.connection import Client
from src.workflows.fargate.config import TEMPORAL_NAMESPACE, TEMPORAL_URL, TEMPORAL_API_KEY
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from pydantic import BaseModel

    from src.workflows.fargate.fargate_activities import (
        FargateSandboxConfig,
        FireAndForgetSandboxInput,
        FireAndForgetSandboxOutput,
        LongRunningSandboxInput,
        SandboxResult,
        SandboxStatus,
        start_sandbox_and_poll,
        start_sandbox_fire_and_forget,
    )


class FargateSandboxWorkflowInput(BaseModel):
    """Input model for the Fargate sandbox orchestration workflow."""

    run_label: str
    """Logical label for this orchestration run (for example, agent name)."""

    cluster: str
    """Name or ARN of the ECS cluster used for sandboxes."""

    task_definition: str
    """Name or ARN of the ECS task definition for coding agents."""

    subnets: list[str]
    """Subnets used for sandbox networking."""

    polling_interval_seconds: int = 30
    """Interval between polls in the long-running Activity."""

    max_polls: int = 10
    """Maximum number of polls before treating the sandbox as completed."""


class FargateSandboxWorkflowOutput(BaseModel):
    """Output model for the Fargate sandbox orchestration workflow."""

    polling_pattern_result: SandboxResult
    """Result observed from the polling Activity pattern."""

    signal_pattern_result: SandboxResult
    """Result observed from the signal-based pattern."""


@workflow.defn
class FargateSandboxWorkflow:
    """Workflow demonstrating polling and signal patterns for Fargate sandboxes."""

    def __init__(self) -> None:
        self._async_sandbox_result: SandboxResult | None = None

    @workflow.run
    async def run(self, input: FargateSandboxWorkflowInput) -> FargateSandboxWorkflowOutput:
        """Run the Fargate sandbox orchestration workflow."""
        workflow.logger.info(
            "Starting Fargate sandbox orchestration for %s (cluster=%s task_definition=%s)",
            input.run_label,
            input.cluster,
            input.task_definition,
        )

        # Shared configuration used for both patterns. Filesystem isolation is
        # provided by how the Fargate task is configured (EFS, S3, ephemeral
        # storage) rather than by Temporal itself.
        config = FargateSandboxConfig(
            cluster=input.cluster,
            task_definition=input.task_definition,
            subnets=input.subnets,
            assign_public_ip=False,
        )

        # --- Pattern 1: long-running Activity that polls and heartbeats ---
        long_running_request = LongRunningSandboxInput(
            config=config,
            poll_interval_seconds=input.polling_interval_seconds,
            max_polls=input.max_polls,
        )

        polling_result: SandboxResult = await workflow.execute_activity(
            start_sandbox_and_poll,
            long_running_request,
            # For genuinely long-running sandboxes this timeout would often be
            # hours. Heartbeats allow Temporal to detect a dead task and retry.
            start_to_close_timeout=timedelta(hours=4),
        )

        # --- Pattern 2: fire-and-forget Activity plus signal from sandbox ---
        fire_and_forget_request = FireAndForgetSandboxInput(config=config)

        fire_and_forget_result: FireAndForgetSandboxOutput = await workflow.execute_activity(
            start_sandbox_fire_and_forget,
            fire_and_forget_request,
            start_to_close_timeout=timedelta(seconds=30),
        )

        awaited_sandbox_id = fire_and_forget_result.sandbox_id
        workflow.logger.info(
            "Waiting for sandbox %s to signal completion", awaited_sandbox_id
        )

        def _signal_received_for_expected_sandbox() -> bool:
            return (
                self._async_sandbox_result is not None
                and self._async_sandbox_result.sandbox_id == awaited_sandbox_id
            )

        # Block the Workflow until the Fargate task (or a test) signals that
        # the sandbox completed. Because this is a Workflow wait, it is fully
        # replay-safe and does not tie up any OS threads.
        await workflow.wait_condition(_signal_received_for_expected_sandbox)

        signal_result = self._async_sandbox_result
        if signal_result is None:  # Defensive, should not happen.
            raise RuntimeError("Signal-based sandbox result was not set on the Workflow.")

        workflow.logger.info(
            "Fargate sandbox orchestration complete for %s; polling sandbox=%s signal sandbox=%s",
            input.run_label,
            polling_result.sandbox_id,
            signal_result.sandbox_id,
        )

        return FargateSandboxWorkflowOutput(
            polling_pattern_result=polling_result,
            signal_pattern_result=signal_result,
        )

    @workflow.signal
    def sandbox_completed(
        self,
        sandbox_id: str,
        status: SandboxStatus,
        result_payload: str | None = None,
    ) -> None:
        """Signal invoked by Fargate tasks when a sandbox finishes.

        In a real deployment, the Fargate task would authenticate to the
        Temporal Cluster and send this signal when the coding agent run
        completes. The Workflow then becomes the single source of truth for
        sandbox status across retries and restarts.
        """
        workflow.logger.info(
            "Received completion signal from sandbox %s with status %s",
            sandbox_id,
            status,
        )
        self._async_sandbox_result = SandboxResult(
            sandbox_id=sandbox_id,
            status=status,
            result_payload=result_payload,
        )

    @workflow.query
    def async_sandbox_status(self) -> SandboxResult | None:
        """Query the latest known status for the async (signal-based) sandbox."""
        return self._async_sandbox_result


async def main() -> None:  # pragma: no cover
    """Connects to the client and executes the Fargate sandbox workflow."""
    import uuid  # noqa: PLC0415

    from temporalio.client import Client  # noqa: PLC0415
    from temporalio.contrib.pydantic import (  # noqa: PLC0415
        pydantic_data_converter,
    )

    client = await Client.connect(TEMPORAL_URL, namespace=TEMPORAL_NAMESPACE, api_key=TEMPORAL_API_KEY, data_converter=pydantic_data_converter, tls=True)
    input_data = FargateSandboxWorkflowInput(
        run_label="example-fargate-sandbox-run",
        cluster="example-cluster",
        task_definition="coding-agent-task-definition",
        subnets=["subnet-123456"],
        polling_interval_seconds=10,
        max_polls=3,
    )

    result = await client.execute_workflow(
        FargateSandboxWorkflow.run,
        input_data,
        id=f"fargate-sandbox-workflow-{uuid.uuid4()}",
        task_queue="fargate-sandbox-task-queue",
    )

    print(f"Fargate Sandbox Workflow Result: {result}")  # noqa: T201


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
