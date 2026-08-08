"""Automated evaluation harness for RAG pipelines.

Integrates DeepEval, RAGAS, and LangSmith for comprehensive quality assessment.
Runs 100+ golden test cases, detects regressions, and tracks quality trends.
"""

from .harness import EvalHarness, EvalResult, QualityMetrics
from .golden_cases import GoldenTestCase, load_golden_cases
from .evaluators import DeepEvalEvaluator, RAGASEvaluator, LangSmithTracer
from .regression_detector import RegressionDetector

__all__ = [
    "EvalHarness",
    "EvalResult",
    "QualityMetrics",
    "GoldenTestCase",
    "load_golden_cases",
    "DeepEvalEvaluator",
    "RAGASEvaluator",
    "LangSmithTracer",
    "RegressionDetector",
]
