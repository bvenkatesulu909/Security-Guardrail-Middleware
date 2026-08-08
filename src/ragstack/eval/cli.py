"""CLI for running the automated evaluation harness."""

import asyncio
import json
from pathlib import Path
from typing import Optional
import click

from .harness import EvalHarness
from .golden_cases import load_golden_cases


def create_default_executor():
    """Create a default RAG executor using the PDF QA system.

    Returns:
        Async function that executes RAG queries
    """

    async def execute(question: str, context: str) -> str:
        """Execute a query through the RAG pipeline.

        Args:
            question: The input question
            context: The retrieval context

        Returns:
            Generated answer
        """
        try:
            from ragstack.pdf_qa.llm_chain import AnswerGenerator

            generator = AnswerGenerator()
            from ragstack.pdf_qa.models import RetrievalResult

            # Create synthetic RetrievalResult objects from context
            chunks = [
                RetrievalResult(
                    chunk_id="context",
                    content=context,
                    relevance_score=1.0,
                    source="input_context",
                )
            ]

            response = generator.generate_answer(question, chunks, include_reasoning=False)
            return response.answer
        except Exception as e:
            return f"Error executing RAG query: {str(e)}"

    return execute


@click.group()
def cli():
    """Automated Evaluation Harness CLI.

    Runs 100+ golden test cases before deployment, detects regressions,
    and tracks quality trends using DeepEval, RAGAS, and LangSmith.
    """
    pass


@cli.command()
@click.option(
    "--skip-slow",
    is_flag=True,
    help="Skip slow/hard test cases for faster feedback",
)
@click.option(
    "--max-tests",
    type=int,
    default=None,
    help="Limit number of tests to run",
)
@click.option(
    "--category",
    type=str,
    default=None,
    help="Only run tests in specific category (factual, completeness, citations, edge_cases, reasoning)",
)
@click.option(
    "--results-dir",
    type=click.Path(),
    default="eval_results",
    help="Directory to save results",
)
@click.option(
    "--block-regressions",
    is_flag=True,
    default=True,
    help="Exit with error code if regressions detected",
)
def run(
    skip_slow: bool,
    max_tests: Optional[int],
    category: Optional[str],
    results_dir: str,
    block_regressions: bool,
):
    """Run the full evaluation suite.

    Executes 100+ golden test cases, evaluates with DeepEval/RAGAS,
    detects regressions, and generates comprehensive report.
    """
    click.echo("🚀 Starting Automated Evaluation Harness...")
    click.echo(f"   Results directory: {results_dir}")

    results_path = Path(results_dir)

    # Create executor
    executor = create_default_executor()

    def sync_executor(question: str, context: str) -> str:
        """Sync wrapper for async executor."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(executor(question, context))
        finally:
            loop.close()

    # Initialize harness
    harness = EvalHarness(
        rag_executor=sync_executor,
        results_dir=results_path,
    )

    # Run tests
    try:
        harness.run_all_tests(
            skip_slow=skip_slow,
            max_tests=max_tests,
            by_category=category,
        )
    except Exception as e:
        click.echo(f"❌ Error running tests: {e}", err=True)
        raise click.Exit(1)

    # Generate report
    report = harness.generate_report()
    click.echo("\n" + report)

    # Save results
    harness.save_results()

    # Check for regressions
    _, regression_summary = harness.detect_regressions()
    should_block = regression_summary["should_block_deploy"]

    if block_regressions and should_block:
        click.echo("\n❌ Deployment blocked due to regressions", err=True)
        raise click.Exit(1)

    click.echo("\n✅ Evaluation complete")


@cli.command()
@click.option(
    "--output",
    type=click.Path(),
    default="golden_cases.json",
    help="Output file for golden cases",
)
def export_cases(output: str):
    """Export golden test cases to JSON file."""
    cases = load_golden_cases()
    with open(output, "w") as f:
        json.dump([c.to_dict() for c in cases], f, indent=2)
    click.echo(f"✅ Exported {len(cases)} golden test cases to {output}")


@cli.command()
@click.option(
    "--results-dir",
    type=click.Path(),
    default="eval_results",
    help="Directory containing evaluation results",
)
def show_trend(results_dir: str):
    """Show quality trend report.

    Displays how metrics have changed over time based on
    historical evaluation runs.
    """
    from .regression_detector import RegressionDetector

    history_file = Path(results_dir) / "metric_history.json"
    detector = RegressionDetector(history_file)

    click.echo(detector.get_trend_report())


@cli.command()
def count_cases():
    """Count total golden test cases available."""
    cases = load_golden_cases()
    click.echo(f"Total golden test cases: {len(cases)}")

    # Count by category
    categories = {}
    for case in cases:
        categories[case.category] = categories.get(case.category, 0) + 1

    click.echo("\nBreakdown by category:")
    for category, count in sorted(categories.items()):
        click.echo(f"  • {category}: {count}")


if __name__ == "__main__":
    cli()
