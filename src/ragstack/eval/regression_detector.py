"""Regression detection and quality trend tracking."""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import json
from pathlib import Path
import statistics

__all__ = ["RegressionResult", "RegressionDetector"]


@dataclass
class RegressionResult:
    """Result of regression detection."""

    is_regression: bool
    metric_name: str
    current_score: float
    baseline_score: float
    change_percent: float
    threshold_percent: float = 5.0  # Default 5% threshold
    message: str = ""
    historical_scores: list[float] = field(default_factory=list)
    trend: str = ""  # "improving", "declining", "stable"


class RegressionDetector:
    """Detects regressions and tracks quality trends.

    Compares current test results against:
    1. Baseline (last known good state)
    2. Historical average
    3. Trend analysis
    """

    def __init__(
        self,
        history_path: Path,
        regression_threshold: float = 5.0,
        min_history: int = 5,
    ):
        """Initialize regression detector.

        Args:
            history_path: Path to history JSON file
            regression_threshold: Regression threshold in percent (default 5%)
            min_history: Minimum historical points for trend analysis
        """
        self.history_path = Path(history_path)
        self.regression_threshold = regression_threshold
        self.min_history = min_history
        self.history = self._load_history()

    def _load_history(self) -> dict:
        """Load historical scores from file.

        Returns:
            Dict mapping metric names to lists of historical scores
        """
        if not self.history_path.exists():
            return {}

        try:
            with open(self.history_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_history(self) -> None:
        """Save history to file."""
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_path, "w") as f:
            json.dump(self.history, f, indent=2)

    def check_regression(
        self, metric_name: str, current_score: float
    ) -> RegressionResult:
        """Check if current score represents a regression.

        Args:
            metric_name: Name of the metric
            current_score: Current score value (0-1 scale)

        Returns:
            RegressionResult indicating if regression detected
        """
        if metric_name not in self.history:
            # First time seeing this metric
            self.history[metric_name] = [current_score]
            self._save_history()
            return RegressionResult(
                is_regression=False,
                metric_name=metric_name,
                current_score=current_score,
                baseline_score=current_score,
                change_percent=0.0,
                message="First measurement for this metric",
                historical_scores=[current_score],
                trend="stable",
            )

        scores = self.history[metric_name]
        baseline = scores[-1]  # Most recent baseline
        historical_avg = statistics.mean(scores) if scores else baseline

        # Calculate change percentage
        if baseline > 0:
            change_percent = ((current_score - baseline) / baseline) * 100
        else:
            change_percent = 0.0

        # Detect trend
        trend = self._detect_trend(scores)

        # Check for regression
        is_regression = change_percent < -self.regression_threshold

        # Build message
        if is_regression:
            message = (
                f"REGRESSION: {metric_name} declined {abs(change_percent):.1f}% "
                f"(from {baseline:.3f} to {current_score:.3f})"
            )
        elif change_percent > self.regression_threshold:
            message = (
                f"IMPROVEMENT: {metric_name} improved {change_percent:.1f}% "
                f"(from {baseline:.3f} to {current_score:.3f})"
            )
        else:
            message = (
                f"STABLE: {metric_name} changed {change_percent:+.1f}% "
                f"(from {baseline:.3f} to {current_score:.3f})"
            )

        # Add to history
        self.history[metric_name].append(current_score)
        self._save_history()

        return RegressionResult(
            is_regression=is_regression,
            metric_name=metric_name,
            current_score=current_score,
            baseline_score=baseline,
            change_percent=change_percent,
            threshold_percent=self.regression_threshold,
            message=message,
            historical_scores=list(scores),
            trend=trend,
        )

    def _detect_trend(self, scores: list[float]) -> str:
        """Detect trend from historical scores.

        Args:
            scores: List of historical scores

        Returns:
            "improving", "declining", or "stable"
        """
        if len(scores) < self.min_history:
            return "insufficient_data"

        recent = scores[-self.min_history :]
        early = scores[: self.min_history]

        recent_avg = statistics.mean(recent)
        early_avg = statistics.mean(early)

        threshold = 0.02  # 2% change to detect trend
        if recent_avg > early_avg * (1 + threshold):
            return "improving"
        elif recent_avg < early_avg * (1 - threshold):
            return "declining"
        else:
            return "stable"

    def check_all_regressions(
        self, metrics: dict[str, float]
    ) -> list[RegressionResult]:
        """Check all metrics for regressions.

        Args:
            metrics: Dict mapping metric names to scores

        Returns:
            List of RegressionResult objects
        """
        return [
            self.check_regression(name, score) for name, score in metrics.items()
        ]

    def get_trend_report(self) -> str:
        """Generate a report of metric trends.

        Returns:
            Formatted trend report
        """
        if not self.history:
            return "No historical data available"

        report_lines = ["Quality Trend Report", "=" * 50]

        for metric_name, scores in sorted(self.history.items()):
            if len(scores) < 2:
                continue

            current = scores[-1]
            baseline = scores[-2] if len(scores) > 1 else scores[0]
            change = ((current - baseline) / baseline * 100) if baseline > 0 else 0

            trend = self._detect_trend(scores)
            status = "📈" if change > 0 else "📉" if change < 0 else "→"

            report_lines.append(
                f"{status} {metric_name}: {current:.3f} ({change:+.1f}%) [{trend}]"
            )

        return "\n".join(report_lines)

    def get_regression_summary(
        self, regression_results: list[RegressionResult]
    ) -> dict:
        """Summarize regression detection results.

        Args:
            regression_results: List of RegressionResult objects

        Returns:
            Summary dict with counts and blocking decision
        """
        total = len(regression_results)
        regressions = sum(1 for r in regression_results if r.is_regression)
        improvements = sum(
            1 for r in regression_results if r.change_percent > self.regression_threshold
        )
        stable = total - regressions - improvements

        should_block = regressions > 0

        return {
            "total_metrics": total,
            "regressions": regressions,
            "improvements": improvements,
            "stable": stable,
            "should_block_deploy": should_block,
            "message": (
                f"❌ DEPLOY BLOCKED: {regressions} regression(s) detected"
                if should_block
                else f"✅ SAFE TO DEPLOY: All metrics stable or improving"
            ),
        }
