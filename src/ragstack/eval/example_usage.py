"""Complete example of using the Automated Evaluation Harness.

This demonstrates all major features:
1. Running the harness programmatically
2. Using pre-deployment checks
3. Integrating with your RAG pipeline
4. Analyzing results
"""

from pathlib import Path
from typing import Optional
import json

from ragstack.eval.harness import EvalHarness
from ragstack.eval.pre_deploy_check import PreDeployChecker
from ragstack.eval.regression_detector import RegressionDetector


# Example 1: Basic RAG Executor
def create_simple_rag_executor():
    """Create a simple RAG executor for demonstration.

    In production, this would be your actual RAG pipeline that:
    1. Retrieves relevant documents
    2. Ranks them by relevance
    3. Generates an answer using an LLM
    """

    def executor(question: str, context: str) -> str:
        """Simple executor that uses Claude."""
        try:
            from anthropic import Anthropic

            client = Anthropic()
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                system="You are a helpful assistant that answers questions based on provided context. Be accurate and concise.",
                messages=[
                    {
                        "role": "user",
                        "content": f"Context:\n{context}\n\nQuestion: {question}\n\nPlease answer based on the context."
                    }
                ]
            )
            return response.content[0].text
        except Exception as e:
            return f"Error: {str(e)}"

    return executor


# Example 2: Run Full Evaluation Suite
def example_run_full_eval():
    """Run the complete evaluation harness."""
    print("=" * 70)
    print("EXAMPLE 1: Run Full Evaluation Suite")
    print("=" * 70)

    executor = create_simple_rag_executor()
    results_dir = Path("eval_results")

    # Initialize harness
    harness = EvalHarness(
        rag_executor=executor,
        results_dir=results_dir,
        regression_threshold=5.0,
        deepeval_threshold=0.7,
        ragas_threshold=0.7,
    )

    # Run all test cases (or subset for demo)
    print(f"\nRunning evaluation suite...")
    print(f"Total golden test cases: {len(harness.golden_cases)}")

    # For demo, just run a few tests
    results = harness.run_all_tests(max_tests=10)

    print(f"Ran {len(results)} tests")
    passed = sum(1 for r in results if r.passed)
    print(f"Tests passed: {passed}/{len(results)}")

    # Compute metrics
    metrics = harness.compute_metrics()
    print(f"\nQuality Metrics:")
    print(f"  Pass Rate: {metrics.pass_rate*100:.1f}%")
    print(f"  DeepEval Score: {metrics.deepeval_score:.3f}")
    print(f"  RAGAS Score: {metrics.ragas_score:.3f}")
    print(f"  Faithfulness: {metrics.faithfulness:.3f}")
    print(f"  Hallucination Rate: {metrics.hallucination_rate:.3f}")

    # Generate report
    print("\n" + "=" * 70)
    print("FULL REPORT")
    print("=" * 70)
    print(harness.generate_report())

    # Save results
    harness.save_results()

    return harness


# Example 3: Pre-Deployment Checks
def example_pre_deploy_check():
    """Run pre-deployment quality checks."""
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Pre-Deployment Quality Checks")
    print("=" * 70)

    executor = create_simple_rag_executor()

    # Configure pre-deploy checker
    checker = PreDeployChecker(
        results_dir=Path("eval_results"),
        min_pass_rate=0.95,
        min_deepeval_score=0.75,
        min_ragas_score=0.75,
        regression_threshold=5.0,
    )

    # Run checks
    print("\nRunning pre-deployment checks...")
    passed, message = checker.run_checks(executor, skip_slow=True, verbose=False)

    print(message)

    if passed:
        print("\n✅ Safe to deploy!")
        return 0
    else:
        print("\n❌ Deployment blocked!")
        return 1


# Example 4: Regression Detection and Trends
def example_regression_detection():
    """Demonstrate regression detection and trend tracking."""
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Regression Detection & Trends")
    print("=" * 70)

    history_file = Path("eval_results/metric_history.json")
    detector = RegressionDetector(
        history_file,
        regression_threshold=5.0,
        min_history=5,
    )

    # Simulate checking metrics over time
    print("\nSimulating metric checks:")

    # First run
    metrics_run1 = {"answer_relevance": 0.85, "faithfulness": 0.82}
    print("\nRun 1 metrics:")
    for name, score in metrics_run1.items():
        result = detector.check_regression(name, score)
        print(f"  {name}: {score:.3f} - {result.message}")

    # Second run (slight improvement)
    print("\nRun 2 metrics (improvement):")
    metrics_run2 = {"answer_relevance": 0.87, "faithfulness": 0.83}
    for name, score in metrics_run2.items():
        result = detector.check_regression(name, score)
        print(f"  {name}: {score:.3f} - {result.message}")

    # Third run (regression)
    print("\nRun 3 metrics (regression detected):")
    metrics_run3 = {"answer_relevance": 0.81, "faithfulness": 0.82}
    for name, score in metrics_run3.items():
        result = detector.check_regression(name, score)
        print(f"  {name}: {score:.3f}")
        print(f"    Trend: {result.trend}")
        print(f"    Regression: {'Yes ❌' if result.is_regression else 'No ✅'}")

    # Show trend report
    print("\n" + detector.get_trend_report())


# Example 5: Analyzing Results
def example_analyze_results():
    """Analyze and interpret evaluation results."""
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Analyzing Results")
    print("=" * 70)

    results_file = Path("eval_results") / "eval_results_latest.json"

    if not results_file.exists():
        print(f"\nNo results file found at {results_file}")
        print("Run example_run_full_eval() first to generate results.")
        return

    with open(results_file) as f:
        results = json.load(f)

    print(f"\nLoaded {len(results)} test results")

    # Analyze by category
    categories = {}
    for result in results:
        category = result.get("metadata", {}).get("category", "unknown")
        if category not in categories:
            categories[category] = {"passed": 0, "total": 0}
        categories[category]["total"] += 1
        if result["passed"]:
            categories[category]["passed"] += 1

    print("\nResults by category:")
    for category in sorted(categories.keys()):
        stats = categories[category]
        pass_rate = stats["passed"] / stats["total"] * 100
        print(f"  {category}: {stats['passed']}/{stats['total']} ({pass_rate:.1f}%)")

    # Find failing tests
    failed_tests = [r for r in results if not r["passed"]]
    if failed_tests:
        print(f"\n{len(failed_tests)} failing tests:")
        for result in failed_tests[:5]:  # Show first 5
            print(f"  • {result['test_id']}: {result['question'][:50]}...")
            if result.get("error"):
                print(f"    Error: {result['error'][:60]}...")
    else:
        print("\n✅ All tests passed!")


# Example 6: Custom Configuration
def example_custom_configuration():
    """Demonstrate custom configuration options."""
    print("\n" + "=" * 70)
    print("EXAMPLE 5: Custom Configuration")
    print("=" * 70)

    executor = create_simple_rag_executor()

    # High-sensitivity configuration (strict standards)
    strict_harness = EvalHarness(
        rag_executor=executor,
        results_dir=Path("eval_results/strict"),
        regression_threshold=2.0,  # Only 2% drop allowed
        deepeval_threshold=0.85,   # High threshold
        ragas_threshold=0.85,
    )

    # Permissive configuration (early development)
    permissive_harness = EvalHarness(
        rag_executor=executor,
        results_dir=Path("eval_results/permissive"),
        regression_threshold=10.0,  # Allow 10% regression
        deepeval_threshold=0.60,
        ragas_threshold=0.60,
    )

    print("\nStrict Configuration:")
    print(f"  Regression threshold: 2%")
    print(f"  DeepEval threshold: 0.85")
    print(f"  RAGAS threshold: 0.85")
    print("  Use for: Production deploys, release gates")

    print("\nPermissive Configuration:")
    print(f"  Regression threshold: 10%")
    print(f"  DeepEval threshold: 0.60")
    print(f"  RAGAS threshold: 0.60")
    print("  Use for: Early development, experimentation")


# Example 7: Integration with CI/CD
def example_ci_cd_integration():
    """Show how to integrate with CI/CD pipelines."""
    print("\n" + "=" * 70)
    print("EXAMPLE 6: CI/CD Integration")
    print("=" * 70)

    print("""
GitHub Actions Example:
------------------------

name: Pre-Deploy Evaluation

on:
  pull_request:
  push:
    branches: [main]

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

      - name: Check for regressions
        run: eval show-trend

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: eval-results
          path: eval_results/


GitLab CI Example:
------------------

eval:
  stage: test
  script:
    - pip install -e ".[eval]"
    - eval run --skip-slow
  artifacts:
    paths:
      - eval_results/
    expire_in: 30 days
  allow_failure: false  # Fail pipeline on regressions


Jenkins Example:
----------------

pipeline {
    stages {
        stage('Evaluate') {
            steps {
                sh '''
                    pip install -e ".[eval]"
                    eval run
                '''
            }
        }
    }
    post {
        always {
            archiveArtifacts artifacts: 'eval_results/**'
        }
    }
}
""")


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("AUTOMATED EVALUATION HARNESS - COMPLETE EXAMPLES")
    print("=" * 70)

    try:
        # Note: Examples 1-3 require API access
        # For demo purposes, only show structure

        print("\n✅ Example 1: Run Full Evaluation Suite")
        print("   See: example_run_full_eval()")

        print("\n✅ Example 2: Pre-Deployment Checks")
        print("   See: example_pre_deploy_check()")

        print("\n✅ Example 3: Regression Detection & Trends")
        example_regression_detection()

        print("\n✅ Example 4: Analyzing Results")
        print("   See: example_analyze_results()")

        print("\n✅ Example 5: Custom Configuration")
        example_custom_configuration()

        print("\n✅ Example 6: CI/CD Integration")
        example_ci_cd_integration()

        print("\n" + "=" * 70)
        print("To run actual examples, set your API keys and call functions:")
        print("  from ragstack.eval.example_usage import *")
        print("  harness = example_run_full_eval()")
        print("=" * 70 + "\n")

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")


if __name__ == "__main__":
    main()
