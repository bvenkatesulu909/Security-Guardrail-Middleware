# CI/CD Integration Guide

Complete examples for integrating the Automated Evaluation Harness into various CI/CD platforms.

## GitHub Actions

### Basic Setup

```yaml
name: Evaluation Suite

on:
  pull_request:
    paths:
      - 'src/ragstack/**'
      - 'pyproject.toml'
  push:
    branches: [main, develop]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for regression detection
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[eval]"
      
      - name: Run evaluation suite
        run: eval run --skip-slow
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
      
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: eval-results
          path: eval_results/
          retention-days: 30
      
      - name: Comment on PR
        if: github.event_name == 'pull_request' && always()
        uses: actions/github-script@v6
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('eval_results/report_*.txt', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: '```\n' + report + '\n```'
            });
```

### Advanced: Regression Blocking

```yaml
name: Pre-Deploy Evaluation

on:
  pull_request:
    branches: [main]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: pip install -e ".[eval]"
      
      - name: Run evaluation suite
        run: eval run --skip-slow
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      
      - name: Check trends
        run: eval show-trend
        continue-on-error: true
      
      - name: Block on regressions
        run: |
          if grep -q "REGRESSION" eval_results/report_*.txt; then
            echo "❌ Regressions detected - blocking merge"
            exit 1
          else
            echo "✅ No regressions detected"
            exit 0
          fi
```

### Matrix Testing (Multiple Configurations)

```yaml
name: Multi-Config Evaluation

on: [pull_request]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']
        model: ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229']
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: pip install -e ".[eval]"
      
      - name: Run evaluation with ${{ matrix.model }}
        run: eval run --skip-slow
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          EVAL_MODEL: ${{ matrix.model }}
      
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: eval-results-${{ matrix.python-version }}-${{ matrix.model }}
          path: eval_results/
```

## GitLab CI

### Basic Pipeline

```yaml
# .gitlab-ci.yml

stages:
  - evaluate
  - report

eval:
  stage: evaluate
  image: python:3.10
  
  script:
    - pip install -e ".[eval]"
    - eval run --skip-slow
  
  artifacts:
    paths:
      - eval_results/
    expire_in: 30 days
    when: always
  
  allow_failure: false
  
  environment:
    name: evaluation
    
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
    LANGSMITH_API_KEY: $LANGSMITH_API_KEY
  
  tags:
    - docker
```

### With Regression Detection

```yaml
stages:
  - evaluate
  - report
  - gate

eval:
  stage: evaluate
  image: python:3.10
  script:
    - pip install -e ".[eval]"
    - eval run
  artifacts:
    paths:
      - eval_results/
    expire_in: 1 week

regression_check:
  stage: gate
  script:
    - |
      if grep -q "REGRESSION" eval_results/report_*.txt; then
        echo "Regressions detected - blocking merge request"
        exit 1
      fi
  dependencies:
    - eval
  only:
    - merge_requests
```

## Jenkins

### Declarative Pipeline

```groovy
// Jenkinsfile

pipeline {
    agent any
    
    options {
        timeout(time: 1, unit: 'HOURS')
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }
    
    environment {
        PYTHONUNBUFFERED = '1'
        ANTHROPIC_API_KEY = credentials('anthropic-api-key')
        LANGSMITH_API_KEY = credentials('langsmith-api-key')
    }
    
    stages {
        stage('Setup') {
            steps {
                sh '''
                    python -m pip install --upgrade pip
                    pip install -e ".[eval]"
                '''
            }
        }
        
        stage('Evaluate') {
            steps {
                sh 'eval run --skip-slow'
            }
        }
        
        stage('Check Regressions') {
            steps {
                script {
                    try {
                        sh 'eval show-trend'
                    } catch (Exception e) {
                        unstable('Trend analysis failed')
                    }
                }
            }
        }
    }
    
    post {
        always {
            archiveArtifacts artifacts: 'eval_results/**', allowEmptyArchive: true
            
            publishHTML([
                reportDir: 'eval_results',
                reportFiles: 'report_*.txt',
                reportName: 'Evaluation Report'
            ])
        }
        
        failure {
            emailext(
                subject: "Evaluation Failed: ${env.JOB_NAME}",
                body: "Check console output at ${env.BUILD_URL}",
                to: '${DEFAULT_RECIPIENTS}'
            )
        }
        
        success {
            echo '✅ Evaluation passed'
        }
    }
}
```

### Scripted Pipeline

```groovy
// Jenkinsfile (Scripted)

node('docker') {
    try {
        stage('Checkout') {
            checkout scm
        }
        
        stage('Setup Python') {
            sh '''
                python -m pip install --upgrade pip
                pip install -e ".[eval]"
            '''
        }
        
        stage('Run Evaluation') {
            withEnv([
                'ANTHROPIC_API_KEY=' + credentials('anthropic-api-key'),
                'LANGSMITH_API_KEY=' + credentials('langsmith-api-key')
            ]) {
                sh 'eval run --skip-slow'
            }
        }
        
        stage('Analyze Results') {
            def report = readFile 'eval_results/report_*.txt'
            echo report
            
            if (report.contains('REGRESSION')) {
                error('Regressions detected - aborting')
            }
        }
        
    } catch (Exception e) {
        currentBuild.result = 'FAILURE'
        throw e
    } finally {
        archiveArtifacts artifacts: 'eval_results/**', allowEmptyArchive: true
    }
}
```

## CircleCI

```yaml
# .circleci/config.yml

version: 2.1

jobs:
  evaluate:
    docker:
      - image: cimg/python:3.10
    
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      LANGSMITH_API_KEY: ${LANGSMITH_API_KEY}
    
    steps:
      - checkout
      
      - restore_cache:
          keys:
            - v1-dependencies-{{ checksum "pyproject.toml" }}
            - v1-dependencies-
      
      - run:
          name: Install dependencies
          command: |
            python -m venv venv
            . venv/bin/activate
            pip install -e ".[eval]"
      
      - save_cache:
          paths:
            - ./venv
          key: v1-dependencies-{{ checksum "pyproject.toml" }}
      
      - run:
          name: Run evaluation suite
          command: |
            . venv/bin/activate
            eval run --skip-slow
      
      - run:
          name: Check for regressions
          command: |
            . venv/bin/activate
            eval show-trend
          when: always
      
      - store_artifacts:
          path: eval_results
          destination: evaluation-results
      
      - store_test_results:
          path: eval_results

workflows:
  version: 2
  evaluate:
    jobs:
      - evaluate:
          filters:
            branches:
              only:
                - main
                - develop
```

## AWS CodePipeline

### CodeBuild buildspec.yml

```yaml
version: 0.2

phases:
  install:
    runtime-versions:
      python: 3.10
    commands:
      - pip install --upgrade pip
      - pip install -e ".[eval]"
  
  build:
    commands:
      - echo "Running evaluation suite..."
      - eval run --skip-slow
      - echo "Checking for regressions..."
      - eval show-trend
  
  post_build:
    commands:
      - |
        if grep -q "REGRESSION" eval_results/report_*.txt; then
          echo "❌ Regressions detected"
          exit 1
        fi
      - echo "✅ All checks passed"

artifacts:
  files:
    - eval_results/**/*
  name: EvaluationResults

env:
  variables:
    ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    LANGSMITH_API_KEY: ${LANGSMITH_API_KEY}
  parameter-store:
    ANTHROPIC_API_KEY: /codebuild/anthropic-api-key
    LANGSMITH_API_KEY: /codebuild/langsmith-api-key
```

## Azure Pipelines

```yaml
# azure-pipelines.yml

trigger:
  - main
  - develop

pr:
  - main

pool:
  vmImage: 'ubuntu-latest'

variables:
  pythonVersion: '3.10'

stages:
  - stage: Evaluate
    jobs:
      - job: RunEvaluation
        displayName: 'Run Evaluation Suite'
        
        steps:
          - task: UsePythonVersion@0
            inputs:
              versionSpec: '$(pythonVersion)'
            displayName: 'Use Python $(pythonVersion)'
          
          - task: Bash@3
            inputs:
              targetType: 'inline'
              script: |
                python -m pip install --upgrade pip
                pip install -e ".[eval]"
            displayName: 'Install dependencies'
          
          - task: Bash@3
            inputs:
              targetType: 'inline'
              script: 'eval run --skip-slow'
            env:
              ANTHROPIC_API_KEY: $(ANTHROPIC_API_KEY)
              LANGSMITH_API_KEY: $(LANGSMITH_API_KEY)
            displayName: 'Run evaluation suite'
          
          - task: Bash@3
            inputs:
              targetType: 'inline'
              script: 'eval show-trend'
            displayName: 'Show trends'
            continueOnError: true
          
          - task: PublishBuildArtifacts@1
            inputs:
              PathtoPublish: 'eval_results'
              ArtifactName: 'evaluation-results'
            displayName: 'Publish results'
            condition: always()
```

## Docker Integration

### Dockerfile for Evaluation

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install -e ".[eval]"

# Copy source
COPY src/ src/

# Default command: run evaluation
CMD ["eval", "run"]

# Environment variables for API keys
ENV ANTHROPIC_API_KEY=""
ENV LANGSMITH_API_KEY=""
```

Usage:
```bash
docker build -t ragstack-eval .
docker run -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY ragstack-eval eval run
```

### Docker Compose

```yaml
version: '3.8'

services:
  evaluate:
    build: .
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      LANGSMITH_API_KEY: ${LANGSMITH_API_KEY}
    volumes:
      - ./eval_results:/app/eval_results
    command: eval run
```

## Pre-Commit Hook

```yaml
# .pre-commit-config.yaml

repos:
  - repo: local
    hooks:
      - id: eval-harness
        name: Automated Evaluation Harness
        entry: bash -c 'pip install -e .[eval] && eval run --skip-slow'
        language: system
        stages: [commit]
        pass_filenames: false
        verbose: true
```

## Best Practices

### 1. Caching Dependencies

Store and cache pip dependencies between runs:
```yaml
# GitHub Actions
- uses: actions/setup-python@v4
  with:
    python-version: '3.10'
    cache: 'pip'

# GitLab CI
cache:
  paths:
    - .cache/pip
```

### 2. Timeouts

Set appropriate timeouts based on test count:
```yaml
# GitHub Actions
timeout-minutes: 45  # For full suite

# Jenkins
timeout(time: 1, unit: 'HOURS')

# GitLab CI
timeout: 1h
```

### 3. Artifact Retention

Keep results for analysis but limit storage:
```yaml
# GitHub Actions
retention-days: 30

# GitLab CI
expire_in: 1 week

# Jenkins
buildDiscarder(logRotator(numToKeepStr: '10'))
```

### 4. Notifications

Alert on failures:
```yaml
# Email notification
emailext(
    subject: "Evaluation Failed",
    body: "Check ${env.BUILD_URL}",
    to: 'team@example.com'
)

# Slack notification
curl -X POST $SLACK_WEBHOOK \
  -d '{"text":"Evaluation failed"}'
```

### 5. Parallel Execution

Run tests in parallel for speed:
```yaml
# GitHub Actions matrix
strategy:
  matrix:
    test-suite: [factual, completeness, citations, edge-cases]
```

## Monitoring & Alerts

### LangSmith Dashboard

Track evaluations in real-time:
```python
from langsmith import Client

client = Client()
# Traces automatically logged when LANGSMITH_API_KEY is set
```

### Custom Metrics

Export to monitoring systems:
```python
import prometheus_client

pass_rate = prometheus_client.Gauge(
    'eval_pass_rate',
    'Percentage of tests passing'
)
pass_rate.set(metrics.pass_rate * 100)
```

## Troubleshooting

### Issue: Timeout in CI/CD

**Solution**: Use `--skip-slow` flag or increase timeout

### Issue: Different results locally vs CI/CD

**Solution**: Ensure API keys are properly configured

### Issue: Out of disk space

**Solution**: Limit artifact retention and clean old results

### Issue: Cost overruns

**Solution**: Use cheaper models for evaluation or sample tests

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [GitLab CI Documentation](https://docs.gitlab.com/ee/ci/)
- [Jenkins Documentation](https://www.jenkins.io/doc/)
- [CircleCI Documentation](https://circleci.com/docs/)
- [AWS CodePipeline Documentation](https://docs.aws.amazon.com/codepipeline/)
- [Azure Pipelines Documentation](https://docs.microsoft.com/en-us/azure/devops/pipelines/)
