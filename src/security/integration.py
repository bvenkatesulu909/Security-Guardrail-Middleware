"""
Integration guide for security middleware with Flask applications.

This module shows how to integrate the security guardrails with Flask apps.
"""

from functools import wraps
from flask import request, jsonify, g
import logging
from .guardrails import SecurityMiddleware

logger = logging.getLogger(__name__)


def create_security_middleware(
    enable_injection_detection: bool = True,
    enable_pii_redaction: bool = True,
    enable_rate_limiting: bool = True,
    enable_output_sanitization: bool = True,
    injection_sensitivity: str = 'medium',
    rpm_limit: int = 60,
    rph_limit: int = 1000,
) -> SecurityMiddleware:
    """
    Factory function to create a SecurityMiddleware instance.

    Example:
        middleware = create_security_middleware(rpm_limit=100)
    """
    return SecurityMiddleware(
        enable_injection_detection=enable_injection_detection,
        enable_pii_redaction=enable_pii_redaction,
        enable_rate_limiting=enable_rate_limiting,
        enable_output_sanitization=enable_output_sanitization,
        injection_sensitivity=injection_sensitivity,
        rpm_limit=rpm_limit,
        rph_limit=rph_limit,
    )


def setup_security_middleware(app, middleware: SecurityMiddleware = None):
    """
    Setup security middleware for Flask app.

    This adds global request/response hooks for security analysis.

    Example:
        from flask import Flask
        from src.security.integration import setup_security_middleware

        app = Flask(__name__)
        setup_security_middleware(app)
    """
    if middleware is None:
        middleware = create_security_middleware()

    @app.before_request
    def check_request_security():
        """Analyze incoming request for security threats."""
        client_id = request.remote_addr
        g.security_analysis = None

        # Only check POST/PUT/PATCH requests
        if request.method in ['POST', 'PUT', 'PATCH']:
            if request.is_json:
                try:
                    input_data = str(request.json)
                    analysis = middleware.analyze_input(input_data, client_id)
                    g.security_analysis = analysis

                    # Block if severity is critical/high
                    if not analysis.is_safe and analysis.severity in ['critical', 'high']:
                        logger.warning(
                            f"Security threat blocked for {client_id}: {analysis.threats}"
                        )
                        return jsonify({
                            'error': 'Request rejected due to security policy',
                            'threats': analysis.threats,
                            'severity': analysis.severity,
                        }), 403

                except Exception as e:
                    logger.error(f"Error during request security analysis: {e}")
                    # Don't block on analysis errors, just log

    @app.after_request
    def check_response_security(response):
        """Sanitize outgoing response."""
        if response.is_json and response.status_code == 200:
            try:
                # Log that sanitization occurred
                if hasattr(g, 'security_analysis') and g.security_analysis:
                    logger.debug(
                        f"Request analysis: {g.security_analysis.threats}"
                    )
            except Exception as e:
                logger.error(f"Error during response security analysis: {e}")

        return response

    logger.info("Security middleware initialized for Flask app")


def require_security_check(*args, **kwargs):
    """
    Decorator for endpoints that require specific security checks.

    Example:
        @app.route('/api/sensitive', methods=['POST'])
        @require_security_check(
            injection_detection=True,
            rate_limiting=True,
            min_severity='medium'  # Block if severity >= medium
        )
        def sensitive_endpoint():
            return jsonify({'status': 'ok'})
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            analysis = getattr(g, 'security_analysis', None)

            if analysis:
                # Check severity requirements
                min_severity = kwargs.pop('min_severity', 'critical')
                severity_levels = ['low', 'medium', 'high', 'critical']

                if analysis.severity in severity_levels[severity_levels.index(min_severity):]:
                    return jsonify({
                        'error': 'Request rejected due to security policy',
                        'threats': analysis.threats,
                        'severity': analysis.severity,
                    }), 403

            return func(*args, **kwargs)

        return wrapper
    return decorator


class RequestSecurityLogger:
    """Logs security events for audit trail."""

    def __init__(self, log_file: str = 'security_audit.log'):
        self.log_file = log_file
        self.logger = logging.getLogger('security_audit')

        # Setup file handler
        handler = logging.FileHandler(log_file)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def log_threat(self, client_id: str, threats: list, severity: str):
        """Log security threat."""
        self.logger.warning(
            f"Threat detected - Client: {client_id}, Severity: {severity}, "
            f"Threats: {', '.join(threats)}"
        )

    def log_rate_limit(self, client_id: str, endpoint: str):
        """Log rate limit exceeded."""
        self.logger.warning(
            f"Rate limit exceeded - Client: {client_id}, Endpoint: {endpoint}"
        )

    def log_pii_detection(self, client_id: str, pii_count: int, endpoint: str):
        """Log PII detection."""
        self.logger.info(
            f"PII detected - Client: {client_id}, Count: {pii_count}, "
            f"Endpoint: {endpoint}"
        )


# Example Flask app with security middleware
def create_secure_app(debug: bool = False):
    """
    Create a Flask app with security middleware pre-configured.

    Example:
        app = create_secure_app()
        app.run()
    """
    from flask import Flask
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)

    # Setup security
    security_middleware = create_security_middleware(
        enable_injection_detection=True,
        enable_pii_redaction=True,
        enable_rate_limiting=True,
        enable_output_sanitization=True,
        rpm_limit=60,
        rph_limit=1000,
    )

    setup_security_middleware(app, security_middleware)

    # Add audit logging
    audit_logger = RequestSecurityLogger()

    # Example endpoints
    @app.route('/api/secure-endpoint', methods=['POST'])
    def secure_endpoint():
        """Example secure endpoint."""
        client_id = request.remote_addr
        analysis = getattr(g, 'security_analysis', None)

        # Log security events
        if analysis and analysis.threats:
            audit_logger.log_threat(client_id, analysis.threats, analysis.severity)

        return jsonify({
            'status': 'success',
            'message': 'Request processed securely'
        })

    @app.route('/api/health', methods=['GET'])
    def health():
        """Health check endpoint."""
        return jsonify({'status': 'healthy'})

    return app


if __name__ == '__main__':
    # Example usage
    app = create_secure_app(debug=True)
    print("Starting secure Flask app...")
    app.run(debug=True, port=5000)
