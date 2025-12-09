"""Behavior tests for Fargate sandbox activities."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from temporalio.testing import ActivityEnvironment

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


class TestFargateSandboxActivities:
    """Behavior tests for Fargate sandbox Activities.

    Tests cover both the long-running polling pattern (with heartbeats)
    and the fire-and-forget launch pattern used by coding agent sandboxes.
    """

    @pytest.mark.asyncio
    async def test_start_sandbox_and_poll_should_heartbeat_and_return_completed_result(
        self,
    ) -> None:
        """Scenario: Long-running sandbox with polling and heartbeating.

        Given a long-running coding agent sandbox configuration
        When the Activity launches the sandbox and polls for completion
        Then it should heartbeat on each poll and return a completed result
        """
        activity_environment = ActivityEnvironment()
        sandbox_config = FargateSandboxConfig(
            cluster="test-cluster",
            task_definition="coding-agent-task",
            subnets=["subnet-1"],
            assign_public_ip=False,
        )
        long_running_input = LongRunningSandboxInput(
            config=sandbox_config,
            poll_interval_seconds=0,
            max_polls=3,
        )

        with patch("temporalio.activity.heartbeat") as mock_heartbeat:
            result = await activity_environment.run(start_sandbox_and_poll, long_running_input)

        assert isinstance(result, SandboxResult)
        assert result.status == SandboxStatus.COMPLETED
        assert result.sandbox_id
        expected_polls = long_running_input.max_polls
        assert mock_heartbeat.call_count == expected_polls

    @pytest.mark.asyncio
    async def test_start_sandbox_fire_and_forget_should_launch_without_heartbeats(
        self,
    ) -> None:
        """Scenario: Fire-and-forget sandbox launch signaling back to the Workflow.

        Given a coding agent sandbox configuration
        When the Activity launches the sandbox without polling
        Then it should return the sandbox identifier and not heartbeat
        """
        activity_environment = ActivityEnvironment()
        sandbox_config = FargateSandboxConfig(
            cluster="test-cluster",
            task_definition="coding-agent-task",
            subnets=["subnet-1"],
            assign_public_ip=False,
        )
        fire_and_forget_input = FireAndForgetSandboxInput(config=sandbox_config)

        with patch("temporalio.activity.heartbeat") as mock_heartbeat:
            result = await activity_environment.run(
                start_sandbox_fire_and_forget,
                fire_and_forget_input,
            )

        assert isinstance(result, FireAndForgetSandboxOutput)
        assert result.sandbox_id
        mock_heartbeat.assert_not_called()
