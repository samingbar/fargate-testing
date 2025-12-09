"""Tests for the Fargate sandbox task entrypoint code."""

from __future__ import annotations

from typing import Any

import pytest

from src.workflows.fargate.fargate_activities import SandboxStatus
from src.workflows.fargate.fargate_task import (
    FARGATE_SANDBOX_ID_ENV,
    TEMPORAL_NAMESPACE_ENV,
    TEMPORAL_TARGET_ENV,
    TEMPORAL_WORKFLOW_ID_ENV,
    TEMPORAL_WORKFLOW_RUN_ID_ENV,
    _require_env,
    main,
)


class TestFargateTask:
    """Behavior tests for the Fargate sandbox task code."""

    def test_require_env_should_raise_on_missing_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scenario: Required environment variable is missing."""
        env_name = "MISSING_ENV_VAR"
        monkeypatch.delenv(env_name, raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            _require_env(env_name)

        assert env_name in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_main_should_signal_workflow_with_sandbox_completion(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Scenario: Sandbox task runs and signals workflow completion.

        The Temporal client is mocked so the test does not require a real
        Temporal server. The test verifies that the correct signal name and
        arguments are sent.
        """

        class FakeHandle:
            def __init__(self) -> None:
                self.signal_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

            async def signal(self, *args: Any, **kwargs: Any) -> None:
                self.signal_calls.append((args, kwargs))

        class FakeClient:
            def __init__(self) -> None:
                self.handles: dict[tuple[str, str | None], FakeHandle] = {}

            def get_workflow_handle(self, workflow_id: str, run_id: str | None = None) -> FakeHandle:
                key = (workflow_id, run_id)
                if key not in self.handles:
                    self.handles[key] = FakeHandle()
                return self.handles[key]

        fake_client = FakeClient()

        async def fake_connect(*_: Any, **__: Any) -> FakeClient:
            return fake_client

        # Patch the Temporal client connect method used in the task.
        import temporalio.client as client_module

        monkeypatch.setattr(client_module.Client, "connect", fake_connect, raising=True)

        workflow_id = "test-workflow-id"
        workflow_run_id = "test-run-id"
        sandbox_id = "sandbox-123"

        # Minimal environment required by the task.
        monkeypatch.setenv(TEMPORAL_TARGET_ENV, "test-target:7233")
        monkeypatch.setenv(TEMPORAL_NAMESPACE_ENV, "test-namespace")
        monkeypatch.setenv(TEMPORAL_WORKFLOW_ID_ENV, workflow_id)
        monkeypatch.setenv(TEMPORAL_WORKFLOW_RUN_ID_ENV, workflow_run_id)
        monkeypatch.setenv(FARGATE_SANDBOX_ID_ENV, sandbox_id)

        await main()

        handle = fake_client.get_workflow_handle(workflow_id, workflow_run_id)
        assert handle.signal_calls, "Expected at least one signal call"

        (args, _kwargs) = handle.signal_calls[0]

        # The task sends three positional arguments to the signal:
        # sandbox_id, SandboxStatus, and a result payload string.
        assert args[0] == sandbox_id
        assert args[1] == SandboxStatus.COMPLETED
        assert isinstance(args[2], str)

