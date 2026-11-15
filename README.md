# Security Guardrail Middleware for LLM Apps

Drop-in security middleware for Flask-based LLM and RAG applications. It sits between users and the model and protects against the most common LLM vulnerabilities.

**Stack:** Python · Flask · Guardrails AI · Anthropic Claude · LangGraph · sqlite-vec

## Features

- **Prompt-injection detection:** flags attempts to override system instructions
- **PII redaction:** detects and masks emails, phone numbers and other personal data before it reaches the model or the logs
- **Output filtering:** sanitizes responses to prevent data leakage
- **Rate limiting:** per-client request throttling
- **Sandboxed execution:** a safe environment for model-generated code
- **RAG integration:** ships with a working RAG backend (`src/ragstack/`) and an evaluation harness (`src/ragstack/eval/`) to show the middleware protecting a real app

## Project structure

```
app_secure.py            # Example Flask app with guardrails enabled
src/security/            # Guardrail middleware
src/ragstack/            # RAG backend used by the demo
src/ragstack/eval/       # Evaluation harness and regression checks
tests/                   # Test suite
```

## Quick start

```bash
pip install -r requirements.txt
python app_secure.py
```

```python
from flask import Flask
from src.security.integration import setup_security_middleware

app = Flask(__name__)
setup_security_middleware(app)   # sensible defaults
```

## Documentation

- `SECURITY_GUARDRAILS_GUIDE.md`: full guide and configuration
- `SECURITY_QUICK_REFERENCE.md`: cheat sheet
- `SECURITY_IMPLEMENTATION_SUMMARY.md`: design decisions

Part of the larger [RAGStack platform](https://github.com/bvenkatesulu909/Agentic-Automation-Pipeline).
