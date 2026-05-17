"""Tests for mutmut_llm.pipeline (re-exports from generators/anthropic.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mutmut_llm.config import LLMConfig
from mutmut_llm.pipeline import GenerationResult
from mutmut_llm.discovery import GenerationTarget as ScopeTarget
from tests.conftest import make_mock_response as _make_mock_response


class TestErrorClassifier:
    def _make_api_exc(self, cls, message="error", status_code=400):
        """Construct an Anthropic HTTP exception."""
        import anthropic

        response = MagicMock()
        response.status_code = status_code
        response.headers = {}
        return cls(message=message, response=response, body=None)

    def test_authentication_error_stops(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.AuthenticationError, status_code=401)
        assert classify_error(exc) == ErrorAction.STOP

    def test_permission_denied_stops(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.PermissionDeniedError, status_code=403)
        assert classify_error(exc) == ErrorAction.STOP

    def test_rate_limit_retries(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.RateLimitError, message="rate limit hit", status_code=429)
        assert classify_error(exc) == ErrorAction.RETRY

    def test_rate_limit_with_spending_limit_stops(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.RateLimitError, message="spending limit exceeded", status_code=429)
        assert classify_error(exc) == ErrorAction.STOP

    def test_rate_limit_with_credit_stops(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.RateLimitError, message="insufficient credit", status_code=429)
        assert classify_error(exc) == ErrorAction.STOP

    def test_internal_server_error_retries(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.InternalServerError, status_code=500)
        assert classify_error(exc) == ErrorAction.RETRY

    def test_timeout_retries(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = anthropic.APITimeoutError(request=MagicMock())
        assert classify_error(exc) == ErrorAction.RETRY

    def test_connection_error_retries(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = anthropic.APIConnectionError(request=MagicMock())
        assert classify_error(exc) == ErrorAction.RETRY

    def test_bad_request_skips(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.BadRequestError, status_code=400)
        assert classify_error(exc) == ErrorAction.SKIP

    def test_not_found_skips(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.NotFoundError, status_code=404)
        assert classify_error(exc) == ErrorAction.SKIP

    def test_unknown_exception_skips(self):
        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = ValueError("unexpected")
        assert classify_error(exc) == ErrorAction.SKIP


class TestTrackedSemaphore:
    async def test_in_flight_starts_at_zero(self):
        from mutmut_llm.pipeline import TrackedSemaphore
        sem = TrackedSemaphore(5)
        assert sem.in_flight == 0

    async def test_in_flight_tracking(self):
        from mutmut_llm.pipeline import TrackedSemaphore
        sem = TrackedSemaphore(2)
        assert sem.in_flight == 0

        async with sem:
            assert sem.in_flight == 1
            async with sem:
                assert sem.in_flight == 2
            assert sem.in_flight == 1
        assert sem.in_flight == 0

    async def test_max_concurrency_enforced(self):
        import asyncio
        from mutmut_llm.pipeline import TrackedSemaphore
        sem = TrackedSemaphore(2)
        acquired = []
        released = asyncio.Event()

        async def worker():
            async with sem:
                acquired.append(1)
                await released.wait()

        tasks = [asyncio.create_task(worker()) for _ in range(3)]
        await asyncio.sleep(0.05)
        assert len(acquired) == 2
        assert sem.in_flight == 2
        released.set()
        await asyncio.gather(*tasks)
        assert sem.in_flight == 0

    async def test_in_flight_accurate_under_concurrent_access(self):
        import asyncio
        from mutmut_llm.pipeline import TrackedSemaphore
        sem = TrackedSemaphore(5)
        max_seen = 0

        async def worker():
            nonlocal max_seen
            async with sem:
                max_seen = max(max_seen, sem.in_flight)
                await asyncio.sleep(0.01)

        await asyncio.gather(*[worker() for _ in range(10)])
        assert max_seen <= 5
        assert sem.in_flight == 0


class TestSigintHandler:
    def test_sigint_sets_cancel_event(self):
        import asyncio
        import os
        import signal
        from mutmut_llm.pipeline import _sigint_handler

        cancel_event = asyncio.Event()
        with _sigint_handler(cancel_event):
            assert not cancel_event.is_set()
            os.kill(os.getpid(), signal.SIGINT)
            assert cancel_event.is_set()

    def test_old_handler_restored(self):
        import asyncio
        import signal
        from mutmut_llm.pipeline import _sigint_handler

        original = signal.getsignal(signal.SIGINT)
        cancel_event = asyncio.Event()
        with _sigint_handler(cancel_event):
            current = signal.getsignal(signal.SIGINT)
            assert current != original
        restored = signal.getsignal(signal.SIGINT)
        assert restored == original

    def test_handler_restored_on_exception(self):
        import asyncio
        import signal
        from mutmut_llm.pipeline import _sigint_handler

        original = signal.getsignal(signal.SIGINT)
        cancel_event = asyncio.Event()
        try:
            with _sigint_handler(cancel_event):
                raise RuntimeError("test error")
        except RuntimeError:
            pass
        restored = signal.getsignal(signal.SIGINT)
        assert restored == original


class TestComputeConcurrency:
    def _cfg(self, min_c=5, max_c=20):
        from mutmut_llm.config import LLMConfig
        return LLMConfig(min_concurrency=min_c, max_concurrency=max_c)

    def test_zero_targets_returns_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        assert _compute_concurrency(0, self._cfg()) == 5

    def test_one_target_returns_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        assert _compute_concurrency(1, self._cfg()) == 5

    def test_six_targets_clamped_to_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 6//3=2 < 5
        assert _compute_concurrency(6, self._cfg()) == 5

    def test_fifteen_targets_equals_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 15//3=5 == min
        assert _compute_concurrency(15, self._cfg()) == 5

    def test_thirty_targets_returns_ten(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 30//3=10
        assert _compute_concurrency(30, self._cfg()) == 10

    def test_sixty_targets_equals_max(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 60//3=20 == max
        assert _compute_concurrency(60, self._cfg()) == 20

    def test_ninety_targets_clamped_to_max(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 90//3=30 > 20
        assert _compute_concurrency(90, self._cfg()) == 20

    def test_custom_min_max_clamped_to_max(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # n=30, min=1, max=5: 30//3=10 > 5
        assert _compute_concurrency(30, self._cfg(min_c=1, max_c=5)) == 5

    def test_custom_min_max_clamped_to_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # n=3, min=10, max=20: 3//3=1 < 10
        assert _compute_concurrency(3, self._cfg(min_c=10, max_c=20)) == 10


class TestCallLlmAndValidateAsync:
    async def test_valid_mutations_returned(self, tmp_path):
        import asyncio
        from mutmut_llm.pipeline import _call_llm_and_validate_async
        from tests.conftest import make_async_mock_client, make_mock_response

        mutations = [
            {"mutated_code": "def f(): return 2", "description": "change constant"},
        ]
        client = make_async_mock_client([make_mock_response(mutations, input_tokens=100, output_tokens=50)])

        target = ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )
        config = LLMConfig(api_key="test-key")
        result = await _call_llm_and_validate_async(client, config, target, 3)

        assert len(result.mutations) == 1
        assert result.mutations[0]["mutated_code"] == "def f(): return 2"
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    async def test_truncated_response_warns(self):
        from mutmut_llm.pipeline import _call_llm_and_validate_async
        from tests.conftest import make_async_mock_client, make_mock_response
        import warnings

        client = make_async_mock_client([make_mock_response([], stop_reason="max_tokens")])
        target = ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )
        config = LLMConfig(api_key="test-key")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await _call_llm_and_validate_async(client, config, target, 3)

        assert any("max_tokens" in str(warning.message) for warning in w)

    async def test_timeout_raises(self):
        import asyncio
        from unittest.mock import AsyncMock
        from mutmut_llm.pipeline import _call_llm_and_validate_async

        async def slow_create(**kwargs):
            await asyncio.sleep(1000)

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=slow_create)

        target = ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )
        config = LLMConfig(api_key="test-key", request_timeout_seconds=10)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                _call_llm_and_validate_async(client, config, target, 3),
                timeout=0.1,
            )

    async def test_syntax_errors_rejected(self):
        from mutmut_llm.pipeline import _call_llm_and_validate_async
        from tests.conftest import make_async_mock_client, make_mock_response

        mutations = [
            {"mutated_code": "def f(): SYNTAX ERROR!!!", "description": "invalid"},
            {"mutated_code": "def f(): return 2", "description": "valid"},
        ]
        client = make_async_mock_client([make_mock_response(mutations)])
        target = ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )
        config = LLMConfig(api_key="test-key")
        result = await _call_llm_and_validate_async(client, config, target, 3)

        assert len(result.mutations) == 1
        assert result.mutations[0]["mutated_code"] == "def f(): return 2"


class TestComputeBackoff:
    def test_attempt_zero(self):
        from mutmut_llm.pipeline import _compute_backoff
        d = _compute_backoff(0, 1.0)
        assert 1.0 <= d <= 1.5

    def test_attempt_one(self):
        from mutmut_llm.pipeline import _compute_backoff
        d = _compute_backoff(1, 1.0)
        assert 2.0 <= d <= 2.5

    def test_attempt_two(self):
        from mutmut_llm.pipeline import _compute_backoff
        d = _compute_backoff(2, 1.0)
        assert 4.0 <= d <= 4.5

    def test_capped_at_thirty(self):
        from mutmut_llm.pipeline import _compute_backoff
        # 1.0 * 2^10 = 1024 >> 30, capped at 30
        d = _compute_backoff(10, 1.0)
        assert 30.0 <= d <= 30.5


class TestCallLlmAsync:
    def _make_target(self):
        from mutmut_llm.discovery import GenerationTarget as ScopeTarget
        return ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )

    def _make_semaphore(self, n=5):
        from mutmut_llm.pipeline import TrackedSemaphore
        return TrackedSemaphore(n)

    async def test_successful_call_returns_result(self):
        import asyncio
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig
        from tests.conftest import make_async_mock_client, make_mock_response

        mutations = [{"mutated_code": "def f(): return 2", "description": ""}]
        client = make_async_mock_client([make_mock_response(mutations)])
        config = LLMConfig(api_key="test-key", max_retries=2)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        result = await _call_llm_async(client, config, target, 3, sem, cancel_event)
        assert len(result.mutations) == 1

    async def test_cancel_event_prevents_call(self):
        import asyncio
        from unittest.mock import AsyncMock
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig

        client = AsyncMock()
        config = LLMConfig(api_key="test-key")
        cancel_event = asyncio.Event()
        cancel_event.set()  # Already cancelled
        sem = self._make_semaphore()
        target = self._make_target()

        result = await _call_llm_async(client, config, target, 3, sem, cancel_event)
        assert result.mutations == []
        client.messages.create.assert_not_called()

    async def test_skip_on_permanent_error(self):
        import asyncio
        import anthropic
        from unittest.mock import AsyncMock, MagicMock
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig

        response = MagicMock()
        response.status_code = 400
        response.headers = {}
        exc = anthropic.BadRequestError(message="bad request", response=response, body=None)

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=exc)
        config = LLMConfig(api_key="test-key", max_retries=2)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        result = await _call_llm_async(client, config, target, 3, sem, cancel_event)
        assert result.mutations == []
        # Should only call once (no retries for SKIP)
        assert client.messages.create.call_count == 1

    async def test_stop_on_fatal_error(self):
        import asyncio
        import anthropic
        from unittest.mock import AsyncMock, MagicMock
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig

        response = MagicMock()
        response.status_code = 401
        response.headers = {}
        exc = anthropic.AuthenticationError(message="invalid key", response=response, body=None)

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=exc)
        config = LLMConfig(api_key="test-key", max_retries=2)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        with pytest.raises(anthropic.AuthenticationError):
            await _call_llm_async(client, config, target, 3, sem, cancel_event)
        assert cancel_event.is_set()

    async def test_retry_on_transient_error(self):
        import asyncio
        import anthropic
        from unittest.mock import AsyncMock, MagicMock, patch
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig
        from tests.conftest import make_mock_response

        response = MagicMock()
        response.status_code = 500
        response.headers = {}
        exc = anthropic.InternalServerError(message="server error", response=response, body=None)

        success_response = make_mock_response([{"mutated_code": "def f(): return 2", "description": ""}])
        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=[exc, success_response])

        config = LLMConfig(api_key="test-key", max_retries=2, base_backoff_seconds=0.001)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        sleep_calls = []
        async def mock_sleep(delay):
            sleep_calls.append(delay)

        with patch("asyncio.sleep", mock_sleep):
            result = await _call_llm_async(client, config, target, 3, sem, cancel_event)

        assert len(result.mutations) == 1
        assert len(sleep_calls) == 1  # One sleep between attempts
        assert client.messages.create.call_count == 2

    async def test_max_retries_exhausted_returns_empty(self):
        import asyncio
        import anthropic
        from unittest.mock import AsyncMock, MagicMock, patch
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig

        response = MagicMock()
        response.status_code = 500
        response.headers = {}
        exc = anthropic.InternalServerError(message="server error", response=response, body=None)

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=exc)

        config = LLMConfig(api_key="test-key", max_retries=2, base_backoff_seconds=0.001)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        async def mock_sleep(delay):
            pass

        with patch("asyncio.sleep", mock_sleep):
            result = await _call_llm_async(client, config, target, 3, sem, cancel_event)

        assert result.mutations == []
        assert client.messages.create.call_count == 3  # 1 initial + 2 retries

