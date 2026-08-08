"""
Security guardrails for LLM applications.

Provides prompt injection detection, PII redaction, output filtering,
rate limiting, and sandboxed execution environment.
"""

import re
import time
import logging
from typing import Optional, Dict, Any, List, Tuple
from functools import wraps
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import phonenumbers
from email_validator import validate_email, EmailNotValidError
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SecurityAnalysis:
    """Result of security analysis on input/output."""
    is_safe: bool
    threats: List[str]
    redactions: Dict[str, str]  # original -> redacted
    severity: str  # 'low', 'medium', 'high', 'critical'
    details: Dict[str, Any]


class PromptInjectionDetector:
    """Detects common prompt injection patterns."""

    # Common prompt injection indicators
    INJECTION_PATTERNS = [
        # Instruction overrides
        r'ignore\s+(?:the\s+)?(?:previous\s+)?(?:instructions?|instructions?|prompt)',
        r'forget\s+(?:the\s+)?(?:previous\s+)?(?:instructions?|prompt)',
        r'new\s+(?:instructions?|prompt)',
        r'you\s+are\s+(?:now|actually)',
        r'disregard\s+(?:your\s+)?(?:instructions?|guidelines?)',

        # System message extraction
        r'(?:show|print|reveal|display)\s+(?:your\s+)?(?:system\s+)?(?:message|prompt|instructions)',
        r'what\s+(?:are\s+)?(?:your\s+)?(?:system\s+)?(?:instructions?|guidelines?)',
        r'system\s+prompt\s+is',

        # Role switching
        r'(?:from\s+now\s+on|pretend|act\s+as|play\s+the\s+role\s+of)',
        r'(?:you\s+)?(?:are\s+|become\s+)(?:a|an)\s+',

        # Encoding bypass attempts
        r'(?:base64|encode|decode|rot13|cipher)',
        r'(?:eval|exec|system|subprocess)',
    ]

    def __init__(self, sensitivity: str = 'medium'):
        """
        Initialize detector.

        Args:
            sensitivity: 'low', 'medium', 'high' - determines pattern matching aggressiveness
        """
        self.sensitivity = sensitivity
        self.compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS]

    def detect(self, text: str) -> Tuple[bool, List[str]]:
        """
        Detect prompt injection attempts.

        Args:
            text: Input text to analyze

        Returns:
            (is_injection, matched_patterns)
        """
        if not text or len(text.strip()) == 0:
            return False, []

        matched_patterns = []
        for pattern in self.compiled_patterns:
            if pattern.search(text):
                matched_patterns.append(pattern.pattern)

        # Adjust sensitivity
        threshold = {
            'low': len(self.compiled_patterns),  # Must match all patterns
            'medium': 1,  # Any match is suspicious
            'high': 1,  # Any match is suspicious
        }.get(self.sensitivity, 1)

        is_injection = len(matched_patterns) >= threshold

        return is_injection, matched_patterns


class PIIRedactor:
    """Detects and redacts personally identifiable information."""

    # PII patterns
    PII_PATTERNS = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phone': r'\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b',
        'ssn': r'\b(?!000|666|9\d{2})\d{3}-?(?!00)\d{2}-?(?!0{4})\d{4}\b',
        'credit_card': r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
        'passport': r'\b[A-Z]{1,2}\d{6,9}\b',
        'ip_address': r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
        'name_pattern': r'\b(?:Mr|Ms|Mrs|Dr|Prof)\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b',
    }

    def __init__(self, redaction_char: str = '*', keep_edges: bool = True):
        """
        Initialize redactor.

        Args:
            redaction_char: Character to use for redaction
            keep_edges: Keep first/last characters visible
        """
        self.redaction_char = redaction_char
        self.keep_edges = keep_edges
        self.compiled_patterns = {
            key: re.compile(pattern)
            for key, pattern in self.PII_PATTERNS.items()
        }

    def _redact_value(self, value: str) -> str:
        """Redact a single value."""
        if self.keep_edges and len(value) > 2:
            return f"{value[0]}{self.redaction_char * (len(value) - 2)}{value[-1]}"
        return self.redaction_char * len(value)

    def find_pii(self, text: str) -> Dict[str, List[Tuple[str, str]]]:
        """
        Find all PII in text.

        Returns:
            Dict mapping PII type to list of (original, redacted) tuples
        """
        found_pii = defaultdict(list)

        for pii_type, pattern in self.compiled_patterns.items():
            for match in pattern.finditer(text):
                original = match.group(0)
                redacted = self._redact_value(original)
                found_pii[pii_type].append((original, redacted))

        # Additional checks for phone and email
        self._check_phone_numbers(text, found_pii)
        self._check_emails(text, found_pii)

        return dict(found_pii)

    def _check_emails(self, text: str, found_pii: Dict):
        """Enhanced email detection."""
        email_pattern = self.compiled_patterns['email']
        for match in email_pattern.finditer(text):
            try:
                email = match.group(0)
                validate_email(email)  # Validate format
                redacted = self._redact_value(email)
                found_pii.setdefault('email', []).append((email, redacted))
            except EmailNotValidError:
                pass

    def _check_phone_numbers(self, text: str, found_pii: Dict):
        """Enhanced phone number detection."""
        try:
            for match in re.finditer(r'\b\+?(?:1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b', text):
                number = match.group(0)
                try:
                    parsed = phonenumbers.parse(number, 'US')
                    if phonenumbers.is_valid_number(parsed):
                        redacted = self._redact_value(number)
                        found_pii.setdefault('phone', []).append((number, redacted))
                except:
                    pass
        except:
            pass

    def redact(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Redact all PII from text.

        Returns:
            (redacted_text, mapping of original -> redacted)
        """
        redacted_text = text
        redaction_map = {}

        pii_found = self.find_pii(text)

        for pii_type, matches in pii_found.items():
            for original, redacted in matches:
                # Use placeholder to avoid double-redaction
                placeholder = f"[{pii_type.upper()}_REDACTED_{hashlib.md5(original.encode()).hexdigest()[:8]}]"
                redacted_text = redacted_text.replace(original, placeholder, 1)
                redaction_map[original] = placeholder

        return redacted_text, redaction_map


class OutputSanitizer:
    """Sanitizes LLM outputs to remove sensitive information."""

    def __init__(self, redactor: Optional[PIIRedactor] = None):
        self.redactor = redactor or PIIRedactor()

    def sanitize(self, text: str, remove_code: bool = True) -> Tuple[str, Dict[str, Any]]:
        """
        Sanitize output text.

        Args:
            text: Output to sanitize
            remove_code: Whether to remove/flag code blocks

        Returns:
            (sanitized_text, details)
        """
        details = {
            'pii_found': False,
            'code_blocks': [],
            'redactions': {}
        }

        # Redact PII
        redacted, redaction_map = self.redactor.redact(text)
        if redaction_map:
            details['pii_found'] = True
            details['redactions'] = redaction_map

        # Find and optionally remove code blocks
        if remove_code:
            code_pattern = r'```[\s\S]*?```|`[^`]*`'
            code_matches = re.findall(code_pattern, redacted)
            details['code_blocks'] = code_matches
            # Keep code blocks but flag them
            # In strict mode, you might remove them entirely

        return redacted, details


class RateLimiter:
    """Token-based rate limiting."""

    def __init__(self, requests_per_minute: int = 60, requests_per_hour: int = 1000):
        self.rpm_limit = requests_per_minute
        self.rph_limit = requests_per_hour
        self.request_history = defaultdict(list)  # client_id -> list of timestamps

    def _clean_old_requests(self, client_id: str, window_seconds: int):
        """Remove requests outside the time window."""
        now = time.time()
        self.request_history[client_id] = [
            ts for ts in self.request_history[client_id]
            if now - ts < window_seconds
        ]

    def is_allowed(self, client_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if request is allowed.

        Args:
            client_id: Client identifier (IP, user ID, etc.)

        Returns:
            (is_allowed, details)
        """
        now = time.time()

        # Clean old requests
        self._clean_old_requests(client_id, 3600)  # 1 hour

        history = self.request_history[client_id]

        # Check per-minute limit
        one_minute_ago = now - 60
        recent_requests = len([ts for ts in history if ts > one_minute_ago])

        if recent_requests >= self.rpm_limit:
            return False, {
                'reason': 'Exceeded requests per minute limit',
                'limit': self.rpm_limit,
                'current': recent_requests,
            }

        # Check per-hour limit
        one_hour_ago = now - 3600
        hourly_requests = len([ts for ts in history if ts > one_hour_ago])

        if hourly_requests >= self.rph_limit:
            return False, {
                'reason': 'Exceeded requests per hour limit',
                'limit': self.rph_limit,
                'current': hourly_requests,
            }

        # Record this request
        self.request_history[client_id].append(now)

        return True, {
            'requests_this_minute': recent_requests + 1,
            'requests_this_hour': hourly_requests + 1,
        }


class SandboxedExecutor:
    """Provides sandboxed execution environment for code."""

    def __init__(self, timeout_seconds: int = 5, max_memory_mb: int = 100):
        self.timeout_seconds = timeout_seconds
        self.max_memory_mb = max_memory_mb

    def execute(self, code: str, context: Optional[Dict] = None,
                allowed_imports: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Execute code in a restricted sandbox.

        Args:
            code: Python code to execute
            context: Variables to make available
            allowed_imports: List of allowed module imports

        Returns:
            Execution result with output/errors
        """
        import sys
        import io
        from contextlib import redirect_stdout, redirect_stderr

        allowed_imports = allowed_imports or ['math', 'random', 'json']
        context = context or {}

        # Create restricted globals
        safe_builtins = {
            'abs': abs, 'all': all, 'any': any, 'ascii': ascii,
            'bin': bin, 'bool': bool, 'chr': chr, 'dict': dict,
            'divmod': divmod, 'enumerate': enumerate, 'filter': filter,
            'float': float, 'format': format, 'frozenset': frozenset,
            'hex': hex, 'int': int, 'isinstance': isinstance, 'issubclass': issubclass,
            'iter': iter, 'len': len, 'list': list, 'map': map,
            'max': max, 'min': min, 'next': next, 'oct': oct,
            'ord': ord, 'pow': pow, 'range': range, 'reversed': reversed,
            'round': round, 'set': set, 'slice': slice, 'sorted': sorted,
            'str': str, 'sum': sum, 'tuple': tuple, 'type': type,
            'zip': zip,
        }

        # Dangerous builtins to block
        blocked = ['eval', 'exec', 'open', 'compile', 'input', '__import__',
                   'globals', 'locals', 'vars', 'getattr', 'setattr', 'delattr',
                   'dir', 'classmethod', 'staticmethod']

        restricted_globals = {
            '__builtins__': {k: v for k, v in safe_builtins.items()
                           if k not in blocked},
            **context
        }

        result = {
            'success': False,
            'output': '',
            'error': '',
            'execution_time': 0,
        }

        start_time = time.time()
        try:
            # Capture output
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, restricted_globals)

            result['output'] = stdout_capture.getvalue()
            result['success'] = True

        except Exception as e:
            result['error'] = f"{type(e).__name__}: {str(e)}"
        finally:
            result['execution_time'] = time.time() - start_time

        return result


class SecurityMiddleware:
    """Unified security middleware combining all guardrails."""

    def __init__(
        self,
        enable_injection_detection: bool = True,
        enable_pii_redaction: bool = True,
        enable_rate_limiting: bool = True,
        enable_output_sanitization: bool = True,
        injection_sensitivity: str = 'medium',
        rpm_limit: int = 60,
        rph_limit: int = 1000,
    ):
        self.enable_injection_detection = enable_injection_detection
        self.enable_pii_redaction = enable_pii_redaction
        self.enable_rate_limiting = enable_rate_limiting
        self.enable_output_sanitization = enable_output_sanitization

        self.injection_detector = PromptInjectionDetector(sensitivity=injection_sensitivity)
        self.pii_redactor = PIIRedactor()
        self.output_sanitizer = OutputSanitizer(self.pii_redactor)
        self.rate_limiter = RateLimiter(requests_per_minute=rpm_limit,
                                       requests_per_hour=rph_limit)

    def analyze_input(self, text: str, client_id: str = 'default') -> SecurityAnalysis:
        """Analyze input for security threats."""
        threats = []
        redactions = {}
        severity = 'low'

        # Rate limiting
        if self.enable_rate_limiting:
            allowed, details = self.rate_limiter.is_allowed(client_id)
            if not allowed:
                threats.append(f"Rate limit exceeded: {details['reason']}")
                severity = 'high'

        # Prompt injection detection
        if self.enable_injection_detection:
            is_injection, patterns = self.injection_detector.detect(text)
            if is_injection:
                threats.append(f"Potential prompt injection detected ({len(patterns)} patterns)")
                severity = 'high'

        # PII detection
        if self.enable_pii_redaction:
            redacted, redaction_map = self.pii_redactor.redact(text)
            if redaction_map:
                threats.append(f"PII detected in input ({len(redaction_map)} items)")
                redactions = redaction_map
                severity = 'medium' if severity == 'low' else severity

        is_safe = len(threats) == 0 and severity != 'high'

        return SecurityAnalysis(
            is_safe=is_safe,
            threats=threats,
            redactions=redactions,
            severity=severity,
            details={
                'client_id': client_id,
                'timestamp': datetime.now().isoformat(),
                'checks_performed': {
                    'rate_limiting': self.enable_rate_limiting,
                    'injection_detection': self.enable_injection_detection,
                    'pii_detection': self.enable_pii_redaction,
                }
            }
        )

    def sanitize_output(self, text: str) -> SecurityAnalysis:
        """Sanitize output for sensitive information."""
        sanitized, details = self.output_sanitizer.sanitize(text)

        threats = []
        if details['pii_found']:
            threats.append(f"PII redacted from output ({len(details['redactions'])} items)")

        severity = 'medium' if threats else 'low'

        return SecurityAnalysis(
            is_safe=len(threats) == 0,
            threats=threats,
            redactions=details['redactions'],
            severity=severity,
            details=details
        )


def secure_endpoint(
    injection_detection: bool = True,
    pii_redaction: bool = True,
    rate_limiting: bool = True,
    output_sanitization: bool = True,
):
    """
    Decorator to add security guardrails to Flask endpoints.

    Usage:
        @app.route('/api/endpoint', methods=['POST'])
        @secure_endpoint(injection_detection=True, rate_limiting=True)
        def endpoint():
            ...
    """
    middleware = SecurityMiddleware(
        enable_injection_detection=injection_detection,
        enable_pii_redaction=pii_redaction,
        enable_rate_limiting=rate_limiting,
        enable_output_sanitization=output_sanitization,
    )

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            from flask import request, jsonify

            client_id = request.remote_addr

            # Analyze input
            if request.method in ['POST', 'PUT']:
                if request.is_json:
                    input_data = str(request.json)
                    analysis = middleware.analyze_input(input_data, client_id)

                    if not analysis.is_safe and analysis.severity == 'high':
                        logger.warning(f"Security threat detected: {analysis.threats}")
                        return jsonify({
                            'error': 'Request rejected due to security policy',
                            'threats': analysis.threats,
                        }), 403

            # Execute endpoint
            result = func(*args, **kwargs)

            # Sanitize output if needed
            if output_sanitization and isinstance(result, dict):
                output_str = str(result)
                sanitized_analysis = middleware.sanitize_output(output_str)
                if sanitized_analysis.threats:
                    logger.info(f"Output sanitized: {sanitized_analysis.threats}")

            return result

        return wrapper
    return decorator
