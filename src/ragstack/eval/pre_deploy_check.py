"""Pre-deployment quality checks using the evaluation harness.

This script is meant to be run in CI/CD pipelines before deploying.
It blocks deployment if:
1. Any regression is detected in key metrics
2. Pass rate drops below threshold
3. Critical quality metrics fail

Exit codes:
- 0: All checks passed, safe to deploy
- 1: Regressions or quality issues detected, deployment blocked
- 2: Error running checks
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

from .harness import EvalHarness
from .golden_cases import load_golden_cases


class PreDeployChecker:
    """Runs pre-deployment quality checks."""

    def __init__(
        self,
        results_dir: Path = Path("eval_results"),
        min_pass_rate: float = 0.95,
        min_deepeval_score: float = 0.75,
        min_ragas_score: float = 0.75,
        regression_threshold: float = 5.0,
        timeout_minutes: int = 30,
    ):
        """Initialize pre-deploy checker.

        Args:
            results_dir: Directory for saving results
            min_pass_rate: Minimum pass rate threshold (default 95%)
            min_deepeval_score: Minimum DeepEval score (0-1)
            min_ragas_score: Minimum RAGAS score (0-1)
            regression_threshold: Regression threshold in percent
            timeout_minutes: Maximum time allowed for checks
        """
        self.results_dir = Path(results_dir)
        self.min_pass_rate = min_pass_rate
        self.min_deepeval_score = min_deepeval_score
        self.min_ragas_score = min_ragas_score
        self.regression_threshold = regression_threshold
        self.timeout_minutes = timeout_minutes

    def run_checks(
        self,
        executor,
        skip_slow: bool = True,
        verbose: bool = False,
    ) -> tuple[bool, str]:
        """Run all pre-deployment checks.

        Args:
            executor: Function that executes RAG queries (question, context) -> answer
            skip_slow: Skip slow/hard tests for faster feedback
            verbose: Print detailed output

        Returns:
            Tuple of (all_checks_passed, detailed_message)
        """
        if verbose:
            print("🔍 Running pre-deployment quality checks...")
            print(f"   Results directory: {self.results_dir}")
            print(f"   Minimum pass rate: {self.min_pass_rate*100:.0f}%")
            print(f"   Minimum DeepEval score: {self.min_deepeval_score:.2f}")
            print(f"   Minimum RAGAS score: {self.min_ragas_score:.2f}")
            print(f"   Regression threshold: {self.regression_threshold}%")
            print()

        # Initialize harness
        harness = EvalHarness(
            rag_executor=executor,
            results_dir=self.results_dir,
            regression_threshold=self.regression_threshold,
        )

        # Run evaluation suite
        try:
            harness.run_all_tests(skip_slow=skip_slow)
        except Exception as e:
            return False, f"Error running evaluation suite: {str(e)}"

        # Compute metrics
        metrics = harness.compute_metrics()

        # Check pass rate
        if metrics.pass_rate < self.min_pass_rate:
            return (
                False,
                f"❌ Pass rate too low: {metrics.pass_rate*100:.1f}% "
                f"(minimum: {self.min_pass_rate*100:.0f}%)",
            )

        # Check DeepEval score
        if metrics.deepeval_score > 0 and metrics.deepeval_score < self.min_deepeval_score:
            return (
                False,
                f"❌ DeepEval score too low: {metrics.deepeval_score:.3f} "
                f"(minimum: {self.min_deepeval_score:.2f})",
            )

        # Check RAGAS score
        if metrics.ragas_score > 0 and metrics.ragas_score < self.min_ragas_score:
            return (
                False,
                f"❌ RAGAS score too low: {metrics.ragas_score:.3f} "
                f"(minimum: {self.min_ragas_score:.2f})",
            )

        # Check for regressions
        regression_results, regression_summary = harness.detect_regressions()
        if regression_summary["should_block_deploy"]:
            regression_details = "\n".join(
                f"  • {r.metric_name}: {r.message}"
                for r in regression_results
                if r.is_regression
            )
            return (
                False,
                f"❌ Regressions detected:\n{regression_details}",
            )

        # All checks passed
        if verbose:
            print(harness.generate_report())

        # Save results for audit trail
        harness.save_results()

        return True, "✅ All pre-deployment checks passed"


def main(
    executor=None,
    results_dir: Optional[Path] = None,
    verbose: bool = True,
):
    """Main entry point for pre-deployment checks.

    Args:
        executor: Custom RAG executor function (if None, uses default)
        results_dir: Directory for results (if None, uses default)
        verbose: Print detailed output

    Returns:
        Exit code (0 = success, 1 = checks failed, 2 = error)
    """
    if results_dir is None:
        results_dir = Path("eval_results")

    # Use default executor if not provided
    if executor is None:
        def executor(question: str, context: str) -> str:
            """Default executor using PDF QA system."""
            try:
                from ragstack.pdf_qa.llm_chain import AnswerGenerator
                from ragstack.pdf_qa.models import RetrievalResult

                generator = AnswerGenerator()
                chunks = [
                    RetrievalResult(
                        chunk_id="context",
                        content=context,
                        relevance_score=1.0,
                        source="input_context",
                    )
                ]
                response = generator.generate_answer(question, chunks)
                return response.answer
            except Exception as e:
                return f"Error: {str(e)}"

    # Run checks
    checker = PreDeployChecker(
        results_dir=results_dir,
        min_pass_rate=0.95,
        min_deepeval_score=0.75,
        min_ragas_score=0.75,
        regression_threshold=5.0,
    )

    passed, message = checker.run_checks(executor, skip_slow=True, verbose=verbose)

    if verbose:
        print(message)

    if passed:
        print("\n✅ Safe to deploy")
        return 0
    else:
        print("\n❌ Deployment blocked", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(verbose=True))
