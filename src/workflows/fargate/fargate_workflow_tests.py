"""Behavior tests for the Fargate sandbox orchestration workflow."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from src.workflows.fargate.fargate_activities import FireAndForgetSandboxInput, FireAndForgetSandboxOutput, LongRunningSandboxInput, SandboxResult, SandboxStatus
from src.workflows.fargate.fargate_workflow import (
    FargateSandboxWorkflow,
    FargateSandboxWorkflowInput,
    FargateSandboxWorkflowOutput,
)


class TestFargateSandboxWorkflow:
    """Behavior tests for the FargateSandboxWorkflow.

    Tests demonstrate both orchestration patterns:

    - Long-running Activity that polls a Fargate sandbox and heartbeats.
    - Fire-and-forget Activity where the sandbox signals the Workflow.
    """

    @pytest.fixture
    def task_queue(self) -> str:
        """Generate unique task queue name for each test."""
        return f"test-fargate-sandbox-{uuid.uuid4()}"

    @pytest.mark.asyncio
    async def test_fargate_workflow_should_use_polling_and_signal_patterns(
        self,
        client: Client,
        task_queue: str,
    ) -> None:
        """Scenario: Orchestrating coding agents in Fargate sandboxes.

        Given a user wants to run coding agents in isolated Fargate sandboxes
        When the Workflow orchestrates both polling and signal-based patterns
        Then it should return results from both patterns successfully
        """

        @activity.defn(name="start_sandbox_and_poll")
        async def start_sandbox_and_poll_mock(
            input_data: LongRunningSandboxInput,
        ) -> SandboxResult:
            """Mocked Activity for long-running polling pattern."""
            activity.logger.info(
                "Mocked polling sandbox Activity for task %s",
                input_data.config.task_definition,
            )
            return SandboxResult(
                sandbox_id="sandbox-polling-123",
                status=SandboxStatus.COMPLETED,
                result_payload="polled-result",
            )

        @activity.defn(name="start_sandbox_fire_and_forget")
        async def start_sandbox_fire_and_forget_mock(
            input_data: FireAndForgetSandboxInput,
        ) -> FireAndForgetSandboxOutput:
            """Mocked Activity for fire-and-forget pattern."""
            activity.logger.info(
                "Mocked fire-and-forget sandbox Activity for task %s",
                input_data.config.task_definition,
            )
            return FireAndForgetSandboxOutput(sandbox_id="sandbox-signal-456")

        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[FargateSandboxWorkflow],
            activities=[start_sandbox_and_poll_mock, start_sandbox_fire_and_forget_mock],
            activity_executor=ThreadPoolExecutor(5),
        ):
            workflow_input = FargateSandboxWorkflowInput(
                run_label="test-fargate-run",
                cluster="test-cluster",
                task_definition="coding-agent-task",
                subnets=["subnet-1"],
                polling_interval_seconds=0,
                max_polls=3,
            )

            handle = await client.start_workflow(
                FargateSandboxWorkflow.run,
                workflow_input,
                id=f"fargate-sandbox-{uuid.uuid4()}",
                task_queue=task_queue,
            )

            # Simulate the Fargate task signaling completion back to the Workflow.
            await handle.signal(
                FargateSandboxWorkflow.sandbox_completed,
                sandbox_id="sandbox-signal-456",
                status=SandboxStatus.COMPLETED,
                result_payload="signal-result",
            )

            result = await handle.result()

            assert isinstance(result, FargateSandboxWorkflowOutput)

            # Polling pattern assertions
            assert result.polling_pattern_result.sandbox_id == "sandbox-polling-123"
            assert result.polling_pattern_result.status == SandboxStatus.COMPLETED
            assert result.polling_pattern_result.result_payload == "polled-result"

            # Signal-based pattern assertions
            assert result.signal_pattern_result.sandbox_id == "sandbox-signal-456"
            assert result.signal_pattern_result.status == SandboxStatus.COMPLETED
            assert result.signal_pattern_result.result_payload == "signal-result"
