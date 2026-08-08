"""Main evaluation harness orchestrating all evaluations."""

from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime
from pathlib import Path
import json
import time

from .golden_cases import GoldenTestCase, load_golden_cases
from .evaluators import (
    DeepEvalEvaluator,
    RAGASEvaluator,
    LangSmithTracer,
    EvaluationScore,
)
from .regression_detector import RegressionDetector, RegressionResult

__all__ = ["EvalResult", "QualityMetrics", "EvalHarness"]


@dataclass
class QualityMetrics:
    """Aggregated quality metrics from all evaluators."""

    # Metric scores (0-1 scale)
    answer_relevance: float = 0.0
    faithfulness: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0
    hallucination_rate: float = 0.0

    # Aggregate scores
    deepeval_score: float = 0.0
    ragas_score: float = 0.0

    # Test coverage
    tests_passed: int = 0
    tests_failed: int = 0
    tests_total: int = 0

    # Trend data
    pass_rate: float = 0.0
    regression_detected: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "answer_relevance": self.answer_relevance,
            "faithfulness": self.faithfulness,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
            "hallucination_rate": self.hallucination_rate,
            "deepeval_score": self.deepeval_score,
            "ragas_score": self.ragas_score,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "tests_total": self.tests_total,
            "pass_rate": self.pass_rate,
            "regression_detected": self.regression_detected,
        }


@dataclass
class EvalResult:
    """Result of a single test case evaluation."""

    test_id: str
    question: str
    expected_answer: str
    actual_answer: str
    passed: bool
    deepeval_scores: list[EvaluationScore] = field(default_factory=list)
    ragas_scores: list[EvaluationScore] = field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "test_id": self.test_id,
            "question": self.question,
            "expected_answer": self.expected_answer,
            "actual_answer": self.actual_answer,
            "passed": self.passed,
            "deepeval_scores": [
                {
                    "metric": s.metric_name,
                    "score": s.score,
                    "passed": s.passed,
                    "error": s.error,
                }
                for s in self.deepeval_scores
            ],
            "ragas_scores": [
                {
                    "metric": s.metric_name,
                    "score": s.score,
                    "passed": s.passed,
                    "error": s.error,
                }
                for s in self.ragas_scores
            ],
            "duration_ms": self.duration_ms,
            "error": self.error,
            "metadata": self.metadata,
        }


class EvalHarness:
    """Main evaluation harness.

    Orchestrates:
    1. Loading 100+ golden test cases
    2. Running tests through RAG pipeline
    3. Evaluating with DeepEval, RAGAS, LangSmith
    4. Detecting regressions
    5. Tracking quality trends
    6. Generating reports and blocking deploys
    """

    def __init__(
        self,
        rag_executor: Callable[[str, str], str],
        results_dir: Path = Path("eval_results"),
        history_file: Path = None,
        regression_threshold: float = 5.0,
        deepeval_threshold: float = 0.7,
        ragas_threshold: float = 0.7,
    ):
        """Initialize evaluation harness.

        Args:
            rag_executor: Async function that takes (question, context) -> answer
            results_dir: Directory to save evaluation results
            history_file: Path to metric history file
            regression_threshold: Regression threshold in percent
            deepeval_threshold: DeepEval metric threshold (0-1)
            ragas_threshold: RAGAS metric threshold (0-1)
        """
        self.rag_executor = rag_executor
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.history_file = history_file or self.results_dir / "metric_history.json"
        self.regression_threshold_pct = regression_threshold

        # Initialize evaluators
        self.deepeval = DeepEvalEvaluator(threshold=deepeval_threshold)
        self.ragas = RAGASEvaluator(threshold=ragas_threshold)
        self.langsmith = LangSmithTracer()
        self.regression_detector = RegressionDetector(
            self.history_file, regression_threshold
        )

        # Load golden test cases
        self.golden_cases = load_golden_cases()
        self.eval_results: list[EvalResult] = []

    def run_test(self, test_case: GoldenTestCase) -> EvalResult:
        """Run a single test case.

        Args:
            test_case: The golden test case to run

        Returns:
            EvalResult with evaluation scores
        """
        start_time = time.time()

        try:
            # Execute through RAG pipeline
            answer = self.rag_executor(test_case.question, test_case.context)

            # Evaluate with DeepEval
            deepeval_scores = self.deepeval.evaluate_all(
                test_case.question, answer, test_case.context
            )

            # Evaluate with RAGAS
            ragas_scores = self.ragas.evaluate_all(
                test_case.question, answer, test_case.context
            )

            # Determine pass/fail (all metrics above threshold)
            all_scores = deepeval_scores + ragas_scores
            passed = all(s.passed for s in all_scores if s.error is None)

            duration_ms = (time.time() - start_time) * 1000

            result = EvalResult(
                test_id=test_case.id,
                question=test_case.question,
                expected_answer=test_case.expected_answer,
                actual_answer=answer,
                passed=passed,
                deepeval_scores=deepeval_scores,
                ragas_scores=ragas_scores,
                duration_ms=duration_ms,
                metadata=test_case.metadata or {},
            )

            # Log to LangSmith
            self.langsmith.log_run(
                test_case.id,
                test_case.question,
                answer,
                test_case.context,
                duration_ms=duration_ms,
            )

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return EvalResult(
                test_id=test_case.id,
                question=test_case.question,
                expected_answer=test_case.expected_answer,
                actual_answer="",
                passed=False,
                duration_ms=duration_ms,
                error=str(e),
            )

    def run_all_tests(
        self,
        skip_slow: bool = False,
        max_tests: Optional[int] = None,
        by_category: Optional[str] = None,
    ) -> list[EvalResult]:
        """Run all golden test cases.

        Args:
            skip_slow: Skip slow/hard tests
            max_tests: Limit number of tests to run
            by_category: Only run tests in specific category

        Returns:
            List of EvalResult objects
        """
        # Filter test cases
        cases = self.golden_cases
        if skip_slow:
            cases = [c for c in cases if c.difficulty in ["easy", "medium"]]
        if by_category:
            cases = [c for c in cases if c.category == by_category]
        if max_tests:
            cases = cases[:max_tests]

        print(f"Running {len(cases)} evaluation test cases...")

        self.eval_results = []
        for i, test_case in enumerate(cases, 1):
            print(f"  [{i}/{len(cases)}] {test_case.id}: {test_case.question[:50]}...")
            result = self.run_test(test_case)
            self.eval_results.append(result)

        return self.eval_results

    def compute_metrics(self) -> QualityMetrics:
        """Compute aggregate quality metrics from all test results.

        Returns:
            QualityMetrics object with aggregated scores
        """
        if not self.eval_results:
            return QualityMetrics()

        metrics = QualityMetrics()
        metrics.tests_total = len(self.eval_results)
        metrics.tests_passed = sum(1 for r in self.eval_results if r.passed)
        metrics.tests_failed = metrics.tests_total - metrics.tests_passed
        metrics.pass_rate = (
            metrics.tests_passed / metrics.tests_total
            if metrics.tests_total > 0
            else 0.0
        )

        # Aggregate DeepEval scores
        deepeval_results = [
            score
            for result in self.eval_results
            for score in result.deepeval_scores
            if score.error is None
        ]
        if deepeval_results:
            metrics.deepeval_score = sum(s.score for s in deepeval_results) / len(
                deepeval_results
            )

        # Aggregate RAGAS scores
        ragas_results = [
            score
            for result in self.eval_results
            for score in result.ragas_scores
            if score.error is None
        ]
        if ragas_results:
            metrics.ragas_score = sum(s.score for s in ragas_results) / len(
                ragas_results
            )

        # Compute specific metrics
        faithfulness_scores = [
            s.score
            for result in self.eval_results
            for s in result.deepeval_scores
            if "faithfulness" in s.metric_name and s.error is None
        ]
        if faithfulness_scores:
            metrics.faithfulness = sum(faithfulness_scores) / len(faithfulness_scores)
            metrics.hallucination_rate = 1.0 - metrics.faithfulness

        answer_rel_scores = [
            s.score
            for result in self.eval_results
            for s in result.deepeval_scores
            if "relevance" in s.metric_name and s.error is None
        ]
        if answer_rel_scores:
            metrics.answer_relevance = sum(answer_rel_scores) / len(answer_rel_scores)

        context_prec_scores = [
            s.score
            for result in self.eval_results
            for s in result.ragas_scores
            if "context_precision" in s.metric_name and s.error is None
        ]
        if context_prec_scores:
            metrics.context_precision = sum(context_prec_scores) / len(
                context_prec_scores
            )

        return metrics

    def detect_regressions(self) -> tuple[list[RegressionResult], dict]:
        """Detect regressions from computed metrics.

        Returns:
            Tuple of (regression results, summary dict)
        """
        metrics = self.compute_metrics()
        metric_dict = {
            "answer_relevance": metrics.answer_relevance,
            "faithfulness": metrics.faithfulness,
            "context_precision": metrics.context_precision,
            "pass_rate": metrics.pass_rate,
            "deepeval_score": metrics.deepeval_score,
            "ragas_score": metrics.ragas_score,
        }

        # Filter out zero scores (not computed)
        metric_dict = {k: v for k, v in metric_dict.items() if v > 0}

        regression_results = self.regression_detector.check_all_regressions(
            metric_dict
        )
        summary = self.regression_detector.get_regression_summary(regression_results)

        return regression_results, summary

    def generate_report(self) -> str:
        """Generate comprehensive evaluation report.

        Returns:
            Formatted report string
        """
        metrics = self.compute_metrics()
        regression_results, regression_summary = self.detect_regressions()

        lines = [
            "╔════════════════════════════════════════════════════════════════╗",
            "║           AUTOMATED EVALUATION HARNESS REPORT                  ║",
            "║         (DeepEval + RAGAS + LangSmith Integration)             ║",
            "╚════════════════════════════════════════════════════════════════╝",
            "",
            f"Timestamp: {datetime.now().isoformat()}",
            f"Test Results: {metrics.tests_passed}/{metrics.tests_total} passed ({metrics.pass_rate*100:.1f}%)",
            "",
            "📊 QUALITY METRICS",
            "─" * 64,
            f"DeepEval Score:        {metrics.deepeval_score:.3f}",
            f"RAGAS Score:           {metrics.ragas_score:.3f}",
            f"Answer Relevance:      {metrics.answer_relevance:.3f}",
            f"Faithfulness:          {metrics.faithfulness:.3f}",
            f"Hallucination Rate:    {metrics.hallucination_rate:.3f} (lower is better)",
            f"Context Precision:     {metrics.context_precision:.3f}",
            "",
            "🔍 REGRESSION DETECTION",
            "─" * 64,
            regression_summary["message"],
            f"Total Metrics: {regression_summary['total_metrics']}",
            f"Regressions: {regression_summary['regressions']}",
            f"Improvements: {regression_summary['improvements']}",
            f"Stable: {regression_summary['stable']}",
            "",
            "📈 METRIC TRENDS",
            "─" * 64,
            self.regression_detector.get_trend_report(),
        ]

        if regression_summary["should_block_deploy"]:
            lines.extend(
                [
                    "",
                    "❌ DEPLOYMENT BLOCKED",
                    "─" * 64,
                    "The following metrics show regressions:",
                    "",
                ]
            )
            for r in regression_results:
                if r.is_regression:
                    lines.append(
                        f"  • {r.metric_name}: {r.message}"
                    )
        else:
            lines.extend(
                [
                    "",
                    "✅ SAFE TO DEPLOY",
                    "─" * 64,
                    "All metrics are stable or improving.",
                ]
            )

        return "\n".join(lines)

    def save_results(self) -> Path:
        """Save evaluation results to JSON files.

        Returns:
            Path to results directory
        """
        # Save individual results
        results_data = [r.to_dict() for r in self.eval_results]
        results_file = self.results_dir / f"eval_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, "w") as f:
            json.dump(results_data, f, indent=2)

        # Save aggregated metrics
        metrics = self.compute_metrics()
        metrics_file = self.results_dir / f"metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(metrics_file, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)

        # Save report
        report_file = self.results_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(report_file, "w") as f:
            f.write(self.generate_report())

        print(f"\n✅ Results saved to {self.results_dir}")
        return self.results_dir
