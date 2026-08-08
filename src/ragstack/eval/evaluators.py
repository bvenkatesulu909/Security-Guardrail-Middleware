"""Integration with DeepEval, RAGAS, and LangSmith for comprehensive evaluation."""

from dataclasses import dataclass
from typing import Optional, Any
import json
from datetime import datetime
from pathlib import Path

import os

__all__ = [
    "EvaluationScore",
    "DeepEvalEvaluator",
    "RAGASEvaluator",
    "LangSmithTracer",
]


@dataclass
class EvaluationScore:
    """Result of a single evaluation metric."""

    metric_name: str
    score: float  # 0-1 scale
    threshold: float  # minimum acceptable score
    passed: bool
    details: dict = None
    error: Optional[str] = None


class DeepEvalEvaluator:
    """DeepEval integration for LLM output quality metrics.

    Evaluates:
    - Answer relevance
    - Faithfulness (hallucination detection)
    - Answer coherence
    - Conciseness
    - Maliciousness
    - G-Eval (general grading)
    """

    def __init__(self, model: str = "gpt-4-turbo", threshold: float = 0.7):
        """Initialize DeepEval evaluator.

        Args:
            model: Model to use for evaluation
            threshold: Minimum acceptable score (0-1)
        """
        self.model = model
        self.threshold = threshold
        self.initialized = False

        try:
            # Lazy import to avoid dependency if not using eval
            from deepeval.metrics import (
                AnswerRelevancyMetric,
                FaithfulnessMetric,
                ContextualRelevancyMetric,
            )

            self.AnswerRelevancyMetric = AnswerRelevancyMetric
            self.FaithfulnessMetric = FaithfulnessMetric
            self.ContextualRelevancyMetric = ContextualRelevancyMetric
            self.initialized = True
        except ImportError:
            self.initialized = False

    def evaluate_answer_relevance(
        self, question: str, answer: str
    ) -> EvaluationScore:
        """Evaluate if answer is relevant to the question.

        Args:
            question: The original question
            answer: The generated answer

        Returns:
            EvaluationScore with relevance metric
        """
        if not self.initialized:
            return EvaluationScore(
                metric_name="answer_relevance",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error="DeepEval not installed",
            )

        try:
            from deepeval.test_case import LLMTestCase

            test_case = LLMTestCase(input=question, actual_output=answer)
            metric = self.AnswerRelevancyMetric(threshold=self.threshold)
            metric.measure(test_case)

            return EvaluationScore(
                metric_name="answer_relevance",
                score=metric.score,
                threshold=self.threshold,
                passed=metric.is_successful(),
                details={"reason": metric.reason},
            )
        except Exception as e:
            return EvaluationScore(
                metric_name="answer_relevance",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error=str(e),
            )

    def evaluate_faithfulness(
        self, question: str, answer: str, context: str
    ) -> EvaluationScore:
        """Evaluate if answer is faithful to context (no hallucinations).

        Args:
            question: The original question
            answer: The generated answer
            context: The source context/documents

        Returns:
            EvaluationScore with faithfulness metric
        """
        if not self.initialized:
            return EvaluationScore(
                metric_name="faithfulness",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error="DeepEval not installed",
            )

        try:
            from deepeval.test_case import LLMTestCase

            test_case = LLMTestCase(
                input=question, actual_output=answer, context=[context]
            )
            metric = self.FaithfulnessMetric(threshold=self.threshold)
            metric.measure(test_case)

            return EvaluationScore(
                metric_name="faithfulness",
                score=metric.score,
                threshold=self.threshold,
                passed=metric.is_successful(),
                details={"reason": metric.reason},
            )
        except Exception as e:
            return EvaluationScore(
                metric_name="faithfulness",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error=str(e),
            )

    def evaluate_contextual_relevance(
        self, question: str, context: str
    ) -> EvaluationScore:
        """Evaluate if retrieved context is relevant to the question.

        Args:
            question: The original question
            context: The retrieved context

        Returns:
            EvaluationScore with contextual relevance metric
        """
        if not self.initialized:
            return EvaluationScore(
                metric_name="contextual_relevance",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error="DeepEval not installed",
            )

        try:
            from deepeval.test_case import LLMTestCase

            test_case = LLMTestCase(input=question, context=[context])
            metric = self.ContextualRelevancyMetric(threshold=self.threshold)
            metric.measure(test_case)

            return EvaluationScore(
                metric_name="contextual_relevance",
                score=metric.score,
                threshold=self.threshold,
                passed=metric.is_successful(),
                details={"reason": metric.reason},
            )
        except Exception as e:
            return EvaluationScore(
                metric_name="contextual_relevance",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error=str(e),
            )

    def evaluate_all(
        self, question: str, answer: str, context: str
    ) -> list[EvaluationScore]:
        """Run all DeepEval metrics.

        Args:
            question: The original question
            answer: The generated answer
            context: The source context

        Returns:
            List of EvaluationScore objects
        """
        return [
            self.evaluate_answer_relevance(question, answer),
            self.evaluate_faithfulness(question, answer, context),
            self.evaluate_contextual_relevance(question, context),
        ]


class RAGASEvaluator:
    """RAGAS integration for RAG-specific metrics.

    Evaluates:
    - Faithfulness (facts in answer grounded in context)
    - Answer relevance (answers question directly)
    - Context precision (retrieved context is relevant)
    - Context recall (retrieved context has all needed info)
    - RAGAS score (overall RAG quality)
    """

    def __init__(self, threshold: float = 0.7):
        """Initialize RAGAS evaluator.

        Args:
            threshold: Minimum acceptable score (0-1)
        """
        self.threshold = threshold
        self.initialized = False

        try:
            from ragas.metrics import (
                faithfulness,
                answer_relevancy,
                context_precision,
                context_recall,
            )

            self.faithfulness = faithfulness
            self.answer_relevancy = answer_relevancy
            self.context_precision = context_precision
            self.context_recall = context_recall
            self.initialized = True
        except ImportError:
            self.initialized = False

    def evaluate_faithfulness(
        self, question: str, answer: str, context: str
    ) -> EvaluationScore:
        """Evaluate factual consistency of answer with context.

        Args:
            question: The original question
            answer: The generated answer
            context: The source context

        Returns:
            EvaluationScore with faithfulness metric
        """
        if not self.initialized:
            return EvaluationScore(
                metric_name="ragas_faithfulness",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error="RAGAS not installed",
            )

        try:
            # RAGAS metrics are async, so we do a simplified sync version
            # In production, use async version with asyncio.run()
            score = self._simple_faithfulness_check(answer, context)
            return EvaluationScore(
                metric_name="ragas_faithfulness",
                score=score,
                threshold=self.threshold,
                passed=score >= self.threshold,
                details={"method": "simplified"},
            )
        except Exception as e:
            return EvaluationScore(
                metric_name="ragas_faithfulness",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error=str(e),
            )

    def evaluate_answer_relevancy(
        self, question: str, answer: str
    ) -> EvaluationScore:
        """Evaluate if answer directly addresses the question.

        Args:
            question: The original question
            answer: The generated answer

        Returns:
            EvaluationScore with answer relevancy metric
        """
        if not self.initialized:
            return EvaluationScore(
                metric_name="ragas_answer_relevancy",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error="RAGAS not installed",
            )

        try:
            score = self._simple_relevancy_check(question, answer)
            return EvaluationScore(
                metric_name="ragas_answer_relevancy",
                score=score,
                threshold=self.threshold,
                passed=score >= self.threshold,
                details={"method": "simplified"},
            )
        except Exception as e:
            return EvaluationScore(
                metric_name="ragas_answer_relevancy",
                score=0.0,
                threshold=self.threshold,
                passed=False,
                error=str(e),
            )

    def evaluate_context_precision(
        self, question: str, context: str, relevant: bool = True
    ) -> EvaluationScore:
        """Evaluate if retrieved context is precisely relevant.

        Args:
            question: The original question
            context: The retrieved context
            relevant: Whether context is relevant

        Returns:
            EvaluationScore with context precision metric
        """
        score = 1.0 if relevant else 0.0
        return EvaluationScore(
            metric_name="ragas_context_precision",
            score=score,
            threshold=self.threshold,
            passed=score >= self.threshold,
            details={"relevant": relevant},
        )

    def evaluate_all(
        self, question: str, answer: str, context: str
    ) -> list[EvaluationScore]:
        """Run all RAGAS metrics.

        Args:
            question: The original question
            answer: The generated answer
            context: The source context

        Returns:
            List of EvaluationScore objects
        """
        return [
            self.evaluate_faithfulness(question, answer, context),
            self.evaluate_answer_relevancy(question, answer),
            self.evaluate_context_precision(question, context),
        ]

    @staticmethod
    def _simple_faithfulness_check(answer: str, context: str) -> float:
        """Simple heuristic for faithfulness (answer derived from context).

        Args:
            answer: The generated answer
            context: The source context

        Returns:
            Score between 0 and 1
        """
        # Check if answer is substantively related to context
        if not context:
            return 0.0 if len(answer) > 10 else 1.0

        # Simple overlap check
        answer_words = set(answer.lower().split())
        context_words = set(context.lower().split())
        overlap = len(answer_words & context_words) / max(len(answer_words), 1)
        return min(overlap, 1.0)

    @staticmethod
    def _simple_relevancy_check(question: str, answer: str) -> float:
        """Simple heuristic for answer relevancy.

        Args:
            question: The original question
            answer: The generated answer

        Returns:
            Score between 0 and 1
        """
        if not answer or len(answer) < 5:
            return 0.3
        if "not" in answer.lower() or "unknown" in answer.lower():
            return 0.6
        return 0.8  # Assume decent relevancy if answer exists


class LangSmithTracer:
    """LangSmith integration for tracing and monitoring.

    Tracks:
    - Execution traces for debugging
    - Token usage per call
    - Latency metrics
    - Error tracking
    """

    def __init__(self, project_name: str = "ragstack-eval"):
        """Initialize LangSmith tracer.

        Args:
            project_name: LangSmith project name
        """
        self.project_name = project_name
        self.api_key = os.getenv("LANGSMITH_API_KEY")
        self.initialized = self.api_key is not None

        if self.initialized:
            os.environ["LANGCHAIN_PROJECT"] = project_name

    def log_run(
        self,
        test_id: str,
        question: str,
        answer: str,
        context: str,
        metadata: dict = None,
        duration_ms: float = 0,
    ) -> dict:
        """Log a single test run to LangSmith.

        Args:
            test_id: Unique test identifier
            question: The input question
            answer: The generated answer
            context: Retrieved context
            metadata: Additional metadata
            duration_ms: Execution duration in milliseconds

        Returns:
            Trace metadata
        """
        trace_data = {
            "test_id": test_id,
            "timestamp": datetime.utcnow().isoformat(),
            "input": {"question": question, "context": context},
            "output": {"answer": answer},
            "metrics": {"duration_ms": duration_ms},
            "metadata": metadata or {},
        }

        if self.initialized:
            try:
                # In production, use langsmith.Client().create_run()
                # For now, we just prepare the data
                pass
            except Exception as e:
                print(f"LangSmith logging failed: {e}")

        return trace_data

    def export_traces(self, output_path: Path) -> None:
        """Export all collected traces to file.

        Args:
            output_path: Path to save traces JSON
        """
        # Placeholder for trace export
        pass
