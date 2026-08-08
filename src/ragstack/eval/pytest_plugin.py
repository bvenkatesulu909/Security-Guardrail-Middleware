"""Pytest plugin for integration with the evaluation harness.

Allows running golden test cases as pytest tests with proper reporting.

Usage in pytest.ini:
    [pytest]
    plugins = ragstack.eval.pytest_plugin

Usage in tests:
    # Run specific golden test case
    def test_golden_factual(rag_executor_fixture):
        result = run_golden_test("fac_001", rag_executor_fixture)
        assert result.passed

    # Run all golden test cases
    def test_all_golden_cases(rag_executor_fixture):
        results = run_all_golden_tests(rag_executor_fixture)
        assert all(r.passed for r in results)
"""

import pytest
from typing import Callable, Optional
from pathlib import Path

from .harness import EvalHarness, EvalResult
from .golden_cases import load_golden_cases, GoldenTestCase


@pytest.fixture
def eval_harness(tmp_path: Path) -> EvalHarness:
    """Pytest fixture providing an evaluation harness instance.

    Args:
        tmp_path: Temporary directory for results

    Returns:
        Initialized EvalHarness instance
    """

    def default_executor(question: str, context: str) -> str:
        """Default executor for testing."""
        return f"Answer to '{question}' based on context."

    return EvalHarness(
        rag_executor=default_executor,
        results_dir=tmp_path / "eval_results",
    )


def run_golden_test(
    test_id: str, executor: Callable, eval_harness: Optional[EvalHarness] = None
) -> EvalResult:
    """Run a single golden test case.

    Args:
        test_id: ID of the golden test case (e.g., 'fac_001')
        executor: RAG executor function (question, context) -> answer
        eval_harness: Optional harness instance (will create if not provided)

    Returns:
        EvalResult with detailed scores and pass/fail status

    Example:
        def test_specific_case(rag_executor):
            result = run_golden_test("fac_001", rag_executor)
            assert result.passed, f"Test failed: {result.error}"
    """
    if eval_harness is None:
        eval_harness = EvalHarness(rag_executor=executor)

    # Find test case
    cases = load_golden_cases()
    test_case = next((c for c in cases if c.id == test_id), None)

    if test_case is None:
        raise ValueError(f"Golden test case '{test_id}' not found")

    return eval_harness.run_test(test_case)


def run_all_golden_tests(
    executor: Callable,
    eval_harness: Optional[EvalHarness] = None,
    category: Optional[str] = None,
    max_tests: Optional[int] = None,
) -> list[EvalResult]:
    """Run all (or filtered) golden test cases.

    Args:
        executor: RAG executor function
        eval_harness: Optional harness instance
        category: Only run tests in specific category
        max_tests: Limit number of tests

    Returns:
        List of EvalResult objects

    Example:
        def test_all_golden_cases(rag_executor):
            results = run_all_golden_tests(rag_executor, category="factual")
            pass_rate = sum(1 for r in results if r.passed) / len(results)
            assert pass_rate >= 0.95
    """
    if eval_harness is None:
        eval_harness = EvalHarness(rag_executor=executor)

    return eval_harness.run_all_tests(
        skip_slow=False, max_tests=max_tests, by_category=category
    )


def pytest_addoption(parser):
    """Add command-line options for eval harness."""
    parser.addoption(
        "--eval-skip-slow",
        action="store_true",
        default=False,
        help="Skip slow evaluation tests",
    )
    parser.addoption(
        "--eval-category",
        default=None,
        help="Only run eval tests in specific category",
    )
    parser.addoption(
        "--eval-results-dir",
        default="eval_results",
        help="Directory for saving evaluation results",
    )


def pytest_configure(config):
    """Configure pytest for eval harness."""
    config.addinivalue_line(
        "markers",
        "eval: mark test as an evaluation harness test",
    )
    config.addinivalue_line(
        "markers",
        "eval_slow: mark evaluation test as slow (deselect with -m 'not eval_slow')",
    )


# Example test class that can be used directly
class TestGoldenCases:
    """Example test class using golden test cases."""

    def test_count_golden_cases(self):
        """Verify we have 100+ golden test cases."""
        cases = load_golden_cases()
        assert len(cases) >= 100, f"Expected 100+ cases, got {len(cases)}"

    def test_golden_cases_categories(self):
        """Verify golden cases cover all categories."""
        cases = load_golden_cases()
        categories = {c.category for c in cases}
        expected = {"factual", "completeness", "citations", "edge_cases", "reasoning"}
        assert categories & expected, f"Missing categories: {expected - categories}"

    @pytest.mark.eval
    def test_factual_accuracy(self, eval_harness):
        """Test factual accuracy category."""
        cases = load_golden_cases()
        factual_cases = [c for c in cases if c.category == "factual"][:5]

        passed = 0
        for case in factual_cases:
            result = eval_harness.run_test(case)
            if result.passed:
                passed += 1

        assert passed >= 3, f"Only {passed}/{len(factual_cases)} factual tests passed"

    @pytest.mark.eval
    def test_completeness(self, eval_harness):
        """Test answer completeness category."""
        cases = load_golden_cases()
        completeness_cases = [c for c in cases if c.category == "completeness"][:3]

        if not completeness_cases:
            pytest.skip("No completeness test cases")

        results = [eval_harness.run_test(case) for case in completeness_cases]
        assert len(results) > 0, "No completeness tests ran"

    @pytest.mark.eval
    @pytest.mark.eval_slow
    def test_all_golden_cases(self, eval_harness):
        """Run all golden test cases and report metrics."""
        eval_harness.run_all_tests()
        metrics = eval_harness.compute_metrics()

        assert metrics.tests_passed > 0, "No tests passed"
        assert metrics.pass_rate >= 0.5, f"Pass rate too low: {metrics.pass_rate}"


__all__ = [
    "eval_harness",
    "run_golden_test",
    "run_all_golden_tests",
    "TestGoldenCases",
]
