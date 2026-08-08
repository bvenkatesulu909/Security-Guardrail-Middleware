# Automated Evaluation Harness

Production-grade evaluation system for RAG pipelines using **DeepEval**, **RAGAS**, and **LangSmith**.

## Features

✅ **100+ Golden Test Cases** - Curated test suite covering:
- Factual accuracy
- Answer completeness
- Citation quality
- Edge cases
- Multi-hop reasoning

✅ **Regression Detection** - Automatically blocks deployments when:
- Quality metrics drop > 5% from baseline
- Pass rate falls below threshold
- Critical metrics fail

✅ **Quality Trend Tracking** - Monitor quality over time:
- Historical metric comparisons
- Trend analysis (improving/declining/stable)
- Visual reports with emoji indicators

✅ **Multi-Framework Integration**:
- **DeepEval**: Answer relevance, faithfulness, coherence
- **RAGAS**: Context precision, recall, faithfulness, answer relevancy
- **LangSmith**: Execution tracing, token tracking, latency metrics

✅ **Pre-Deployment Checks** - CI/CD integration with configurable thresholds

## Installation

Add eval dependencies to your environment:

```bash
# Install with eval extras
pip install -e ".[eval]"

# Or install individually
pip install deepeval ragas langsmith
```

## Quick Start

### 1. Run Full Evaluation Suite

```bash
# Run all 100+ test cases
eval run

# Skip slow/hard tests for faster feedback
eval run --skip-slow

# Run specific category only
eval run --category factual

# Limit to N tests
eval run --max-tests 20
```

### 2. Check Pre-Deploy Quality

```python
from ragstack.eval.pre_deploy_check import PreDeployChecker

# Run pre-deployment checks
checker = PreDeployChecker(
    min_pass_rate=0.95,
    min_deepeval_score=0.75,
    min_ragas_score=0.75,
)

def my_rag_executor(question: str, context: str) -> str:
    # Your RAG pipeline here
    return answer

passed, message = checker.run_checks(my_rag_executor)
if passed:
    print("✅ Safe to deploy")
else:
    print(f"❌ {message}")
```

### 3. Integrate with Pytest

```python
# tests/test_eval.py
import pytest
from ragstack.eval.pytest_plugin import run_golden_test, run_all_golden_tests

def test_specific_golden_case(rag_executor):
    """Test a specific golden case."""
    result = run_golden_test("fac_001", rag_executor)
    assert result.passed

def test_all_cases_pass(rag_executor):
    """Test all golden cases."""
    results = run_all_golden_tests(rag_executor, category="factual")
    pass_rate = sum(1 for r in results if r.passed) / len(results)
    assert pass_rate >= 0.95
```

Run with pytest:
```bash
pytest tests/test_eval.py -v
pytest tests/test_eval.py -m eval  # Only eval tests
pytest tests/test_eval.py --eval-skip-slow  # Skip slow tests
```

### 4. Monitor Quality Trends

```bash
# Show trend report
eval show-trend

# Export golden test cases as JSON
eval export-cases --output my_cases.json

# Count total test cases
eval count-cases
```

## Architecture

### Core Components

```
eval/
├── __init__.py              # Package exports
├── harness.py              # Main orchestrator (EvalHarness)
├── golden_cases.py         # 100+ curated test cases
├── evaluators.py           # DeepEval, RAGAS, LangSmith integrations
├── regression_detector.py  # Regression detection & trend tracking
├── cli.py                  # Command-line interface
├── pre_deploy_check.py     # Pre-deployment checker
└── pytest_plugin.py        # Pytest integration
```

### Evaluation Flow

```
Input: Question + Context
    ↓
[RAG Pipeline Execution]
    ↓
Generated Answer
    ↓
┌─────────────────────────────────┐
│  DeepEval Metrics               │
├─────────────────────────────────┤
│ • Answer Relevance (0-1)        │
│ • Faithfulness (0-1)            │
│ • Context Relevance (0-1)       │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│  RAGAS Metrics                  │
├─────────────────────────────────┤
│ • Faithfulness (0-1)            │
│ • Answer Relevancy (0-1)        │
│ • Context Precision (0-1)       │
│ • Context Recall (0-1)          │
└─────────────────────────────────┘
    ↓
[Regression Detection]
    ↓
Result: PASS/FAIL + Metrics + Trend
```

## Metrics Explained

### DeepEval Metrics

- **Answer Relevance**: Is the answer relevant to the question? (0-1)
- **Faithfulness**: Is the answer faithful to the context? (0-1)
- **Contextual Relevance**: Is retrieved context relevant? (0-1)
- **Coherence**: Is the answer coherent and well-structured? (0-1)

### RAGAS Metrics

- **Faithfulness**: Factual consistency with context (0-1)
- **Answer Relevancy**: Does it answer the question? (0-1)
- **Context Precision**: Percentage of relevant context (0-1)
- **Context Recall**: All needed info in context? (0-1)
- **RAGAS Score**: Harmonic mean of all above (0-1)

### Aggregate Scores

- **Pass Rate**: Percentage of tests that passed
- **Hallucination Rate**: 1 - Faithfulness (lower is better)
- **Overall Quality**: Mean of all metric scores

## Test Cases Organization

### By Category

1. **Factual** (25 cases): Direct factual questions
2. **Completeness** (20 cases): Detailed multi-part answers
3. **Citations** (15 cases): Source attribution quality
4. **Edge Cases** (20 cases): Handling unknowns, edge cases
5. **Reasoning** (15 cases): Multi-hop reasoning
6. **General** (30+ cases): Mixed coverage

### By Difficulty

- **Easy**: Basic factual recall
- **Medium**: Synthesis, comparison, simple reasoning
- **Hard**: Multi-hop reasoning, edge cases, domain knowledge

## Configuration

### Regression Thresholds

```python
EvalHarness(
    rag_executor=executor,
    regression_threshold=5.0,        # 5% drop = regression
    deepeval_threshold=0.7,          # Min score for pass
    ragas_threshold=0.7,             # Min score for pass
)
```

### Pre-Deploy Checks

```python
PreDeployChecker(
    min_pass_rate=0.95,              # 95% tests must pass
    min_deepeval_score=0.75,         # Min DeepEval avg
    min_ragas_score=0.75,            # Min RAGAS avg
    regression_threshold=5.0,        # 5% regression threshold
    timeout_minutes=30,              # Max execution time
)
```

## CI/CD Integration

### GitHub Actions

```yaml
name: Pre-Deploy Evaluation

on: [pull_request]

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: pip install -e ".[eval]"
      
      - name: Run evaluation suite
        run: eval run --skip-slow
      
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: eval-results
          path: eval_results/
```

### Pre-Commit Hook

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: eval-harness
      name: Automated Evaluation Harness
      entry: eval run --skip-slow
      language: system
      stages: [commit]
      pass_filenames: false
```

## Output Examples

### CLI Report

```
╔════════════════════════════════════════════════════════════════╗
║           AUTOMATED EVALUATION HARNESS REPORT                  ║
║         (DeepEval + RAGAS + LangSmith Integration)             ║
╚════════════════════════════════════════════════════════════════╝

Timestamp: 2024-01-15T10:30:45.123456
Test Results: 95/100 passed (95.0%)

📊 QUALITY METRICS
──────────────────────────────────────────────────────────────
DeepEval Score:        0.823
RAGAS Score:           0.787
Answer Relevance:      0.845
Faithfulness:          0.812
Hallucination Rate:    0.188 (lower is better)
Context Precision:     0.756

🔍 REGRESSION DETECTION
──────────────────────────────────────────────────────────────
✅ SAFE TO DEPLOY: All metrics stable or improving
Total Metrics: 6
Regressions: 0
Improvements: 2
Stable: 4

📈 METRIC TRENDS
──────────────────────────────────────────────────────────────
📈 answer_relevance: 0.845 (+2.1%) [improving]
→ faithfulness: 0.812 (+0.3%) [stable]
📉 hallucination_rate: 0.188 (-0.3%) [stable]
📈 ragas_score: 0.787 (+1.5%) [improving]
```

### JSON Output

Results are saved to `eval_results/` directory:

```
eval_results/
├── eval_results_20240115_103045.json    # Individual test results
├── metrics_20240115_103045.json         # Aggregated metrics
├── report_20240115_103045.txt           # Text report
└── metric_history.json                  # Historical tracking
```

## Advanced Usage

### Custom Test Cases

```python
from ragstack.eval.golden_cases import GoldenTestCase, save_golden_cases

my_cases = [
    GoldenTestCase(
        id="custom_001",
        category="factual",
        question="What is X?",
        expected_answer="X is...",
        expected_sources=["my_doc.pdf"],
        context="Document content...",
        difficulty="medium",
    ),
]

save_golden_cases(my_cases, Path("custom_cases.json"))

# Load custom cases
from ragstack.eval.golden_cases import load_golden_cases
cases = load_golden_cases(Path("custom_cases.json"))
```

### Custom Evaluator

```python
from ragstack.eval.evaluators import EvaluationScore

class MyCustomEvaluator:
    def evaluate(self, question: str, answer: str, context: str) -> EvaluationScore:
        # Your evaluation logic
        score = compute_score(question, answer, context)
        return EvaluationScore(
            metric_name="my_metric",
            score=score,
            threshold=0.7,
            passed=score >= 0.7,
        )
```

### Real-Time Monitoring

```python
from ragstack.eval.harness import EvalHarness

harness = EvalHarness(executor=my_executor)

# Run tests and stream results
for test_case in harness.golden_cases[:10]:
    result = harness.run_test(test_case)
    print(f"{result.test_id}: {'✅' if result.passed else '❌'}")
    
# Get current metrics anytime
metrics = harness.compute_metrics()
print(f"Pass rate: {metrics.pass_rate*100:.1f}%")
```

## Troubleshooting

### Issue: "DeepEval not installed"

```bash
pip install deepeval
```

### Issue: "RAGAS not installed"

```bash
pip install ragas
```

### Issue: Evaluations too slow

```bash
# Skip slow tests
eval run --skip-slow

# Limit test count
eval run --max-tests 20

# Run only one category
eval run --category factual
```

### Issue: Different results on different runs

Evaluations involve LLM calls which can vary. For deterministic results:
- Use same model and temperature
- Fix random seeds
- Use LangSmith trace replay

## Performance

Typical performance on 100 test cases:

| Configuration | Time | Pass Rate |
|---|---|---|
| Skip slow, skip hard | ~5 min | 95%+ |
| Easy + Medium | ~15 min | 90%+ |
| All 100+ cases | ~30 min | 85%+ |

## Related

- [DeepEval Docs](https://docs.confident-ai.com/)
- [RAGAS Docs](https://docs.ragas.io/)
- [LangSmith Docs](https://docs.smith.langchain.com/)
- [LangChain Docs](https://python.langchain.com/)

## License

Same as ragstack project
