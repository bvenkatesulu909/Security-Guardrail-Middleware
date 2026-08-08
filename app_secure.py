#!/usr/bin/env python3
"""
Interview Preparation Web Application - Secure Version

A full-stack application for interview preparation with security guardrails:
- REST API backend (Flask)
- SQLite database for storing interview prep data
- Dashboard and analytics
- PDF Q&A integration
- Security guardrails (prompt injection detection, PII redaction, rate limiting)

Usage:
    python app_secure.py

Then open: http://localhost:5000
"""

from flask import Flask, render_template, request, jsonify, send_from_directory, g
from flask_cors import CORS
import sqlite3
import json
from datetime import datetime
import os
from pathlib import Path
import logging
from ragstack.pdf_qa import create_qa_graph

# Import security components
from src.security.integration import (
    create_security_middleware,
    setup_security_middleware,
    RequestSecurityLogger,
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Database path
DB_PATH = "interview_prep_app.db"
INTERVIEW_DB = "interview_prep.db"

# Create security middleware
security_middleware = create_security_middleware(
    enable_injection_detection=True,
    enable_pii_redaction=True,
    enable_rate_limiting=True,
    enable_output_sanitization=True,
    injection_sensitivity='medium',
    rpm_limit=100,  # 100 requests per minute
    rph_limit=5000,  # 5000 requests per hour
)

# Setup security middleware
setup_security_middleware(app, security_middleware)

# Setup audit logging
audit_logger = RequestSecurityLogger(
    log_file=os.path.join(os.path.dirname(__file__), 'logs', 'security_audit.log')
)


# Initialize database
def init_db():
    """Initialize SQLite database with required tables."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Interview jobs table
    c.execute('''CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        company_name TEXT NOT NULL,
        position TEXT NOT NULL,
        interview_date TEXT,
        status TEXT DEFAULT 'in_progress',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Practice sessions table
    c.execute('''CREATE TABLE IF NOT EXISTS practice_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER NOT NULL,
        session_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        duration INTEGER,
        questions_practiced INTEGER,
        score REAL,
        notes TEXT,
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )''')

    # Research notes table
    c.execute('''CREATE TABLE IF NOT EXISTS research_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER NOT NULL,
        category TEXT,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )''')

    # Interview questions table
    c.execute('''CREATE TABLE IF NOT EXISTS interview_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        category TEXT,
        answer TEXT,
        difficulty TEXT,
        practiced INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )''')

    # Materials table
    c.execute('''CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        file_name TEXT,
        category TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )''')

    conn.commit()
    conn.close()


def log_security_event(analysis):
    """Log security events from analysis."""
    if analysis and analysis.threats:
        client_id = request.remote_addr
        audit_logger.log_threat(
            client_id,
            analysis.threats,
            analysis.severity
        )

    if analysis and analysis.redactions:
        client_id = request.remote_addr
        audit_logger.log_pii_detection(
            client_id,
            len(analysis.redactions),
            request.path
        )


# Routes

@app.route('/')
def landing():
    """Landing page."""
    return render_template('landing.html')


@app.route('/dashboard')
def dashboard():
    """Main dashboard."""
    return render_template('dashboard.html')


@app.route('/interview/<int:interview_id>')
def interview_detail(interview_id):
    """Interview detail page."""
    return render_template('interview.html', interview_id=interview_id)


@app.route('/practice/<int:interview_id>')
def practice(interview_id):
    """Practice page with mock interview."""
    return render_template('practice.html', interview_id=interview_id)


# API Endpoints

@app.route('/api/users', methods=['POST'])
def create_user():
    """Create new user."""
    data = request.json

    # Log security analysis
    analysis = getattr(g, 'security_analysis', None)
    log_security_event(analysis)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        c.execute('INSERT INTO users (name, email) VALUES (?, ?)',
                 (data['name'], data['email']))
        conn.commit()
        user_id = c.lastrowid

        return jsonify({
            'success': True,
            'user_id': user_id,
            'message': 'User created successfully'
        })
    except sqlite3.IntegrityError:
        return jsonify({
            'success': False,
            'message': 'Email already exists'
        }), 400
    finally:
        conn.close()


@app.route('/api/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    """Get user information."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    conn.close()

    if user:
        return jsonify(dict(user))
    return jsonify({'error': 'User not found'}), 404


@app.route('/api/interviews', methods=['POST'])
def create_interview():
    """Create new interview preparation."""
    data = request.json

    # Log security analysis
    analysis = getattr(g, 'security_analysis', None)
    log_security_event(analysis)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''INSERT INTO interviews
                 (user_id, company_name, position, interview_date, notes)
                 VALUES (?, ?, ?, ?, ?)''',
             (data['user_id'], data['company_name'], data['position'],
              data.get('interview_date'), data.get('notes')))
    conn.commit()
    interview_id = c.lastrowid
    conn.close()

    return jsonify({
        'success': True,
        'interview_id': interview_id,
        'message': 'Interview created successfully'
    })


@app.route('/api/interviews/<int:user_id>', methods=['GET'])
def get_interviews(user_id):
    """Get all interviews for a user."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('SELECT * FROM interviews WHERE user_id = ? ORDER BY created_at DESC',
             (user_id,))
    interviews = [dict(row) for row in c.fetchall()]
    conn.close()

    return jsonify(interviews)


@app.route('/api/interviews/<int:interview_id>', methods=['GET'])
def get_interview(interview_id):
    """Get interview details."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('SELECT * FROM interviews WHERE id = ?', (interview_id,))
    interview = c.fetchone()

    if not interview:
        conn.close()
        return jsonify({'error': 'Interview not found'}), 404

    # Get practice sessions
    c.execute('''SELECT * FROM practice_sessions
                 WHERE interview_id = ?
                 ORDER BY session_date DESC''', (interview_id,))
    sessions = [dict(row) for row in c.fetchall()]

    # Get research notes
    c.execute('''SELECT * FROM research_notes
                 WHERE interview_id = ?
                 ORDER BY created_at DESC''', (interview_id,))
    notes = [dict(row) for row in c.fetchall()]

    # Get questions
    c.execute('''SELECT * FROM interview_questions
                 WHERE interview_id = ?
                 ORDER BY created_at DESC''', (interview_id,))
    questions = [dict(row) for row in c.fetchall()]

    conn.close()

    return jsonify({
        'interview': dict(interview),
        'sessions': sessions,
        'notes': notes,
        'questions': questions
    })


@app.route('/api/interviews/<int:interview_id>', methods=['PUT'])
def update_interview(interview_id):
    """Update interview."""
    data = request.json

    # Log security analysis
    analysis = getattr(g, 'security_analysis', None)
    log_security_event(analysis)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''UPDATE interviews
                 SET company_name = ?, position = ?, interview_date = ?,
                     status = ?, notes = ?
                 WHERE id = ?''',
             (data.get('company_name'), data.get('position'),
              data.get('interview_date'), data.get('status'),
              data.get('notes'), interview_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Interview updated'})


@app.route('/api/research-notes', methods=['POST'])
def add_research_note():
    """Add research note."""
    data = request.json

    # Log security analysis
    analysis = getattr(g, 'security_analysis', None)
    log_security_event(analysis)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''INSERT INTO research_notes
                 (interview_id, category, content)
                 VALUES (?, ?, ?)''',
             (data['interview_id'], data['category'], data['content']))
    conn.commit()
    note_id = c.lastrowid
    conn.close()

    return jsonify({
        'success': True,
        'note_id': note_id,
        'message': 'Note added successfully'
    })


@app.route('/api/questions', methods=['POST'])
def add_question():
    """Add interview question."""
    data = request.json

    # Log security analysis
    analysis = getattr(g, 'security_analysis', None)
    log_security_event(analysis)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''INSERT INTO interview_questions
                 (interview_id, question, category, answer, difficulty)
                 VALUES (?, ?, ?, ?, ?)''',
             (data['interview_id'], data['question'], data.get('category'),
              data.get('answer'), data.get('difficulty', 'medium')))
    conn.commit()
    question_id = c.lastrowid
    conn.close()

    return jsonify({
        'success': True,
        'question_id': question_id,
        'message': 'Question added successfully'
    })


@app.route('/api/questions/<int:question_id>', methods=['PUT'])
def update_question(question_id):
    """Update interview question."""
    data = request.json

    # Log security analysis
    analysis = getattr(g, 'security_analysis', None)
    log_security_event(analysis)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''UPDATE interview_questions
                 SET answer = ?, practiced = practiced + 1
                 WHERE id = ?''',
             (data.get('answer'), question_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Question updated'})


@app.route('/api/practice-sessions', methods=['POST'])
def create_practice_session():
    """Create practice session."""
    data = request.json

    # Log security analysis
    analysis = getattr(g, 'security_analysis', None)
    log_security_event(analysis)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''INSERT INTO practice_sessions
                 (interview_id, duration, questions_practiced, score, notes)
                 VALUES (?, ?, ?, ?, ?)''',
             (data['interview_id'], data.get('duration'),
              data.get('questions_practiced'), data.get('score'),
              data.get('notes')))
    conn.commit()
    session_id = c.lastrowid
    conn.close()

    return jsonify({
        'success': True,
        'session_id': session_id,
        'message': 'Practice session recorded'
    })


@app.route('/api/dashboard/<int:user_id>', methods=['GET'])
def get_dashboard(user_id):
    """Get dashboard statistics."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Total interviews
    c.execute('SELECT COUNT(*) as count FROM interviews WHERE user_id = ?',
             (user_id,))
    total_interviews = c.fetchone()['count']

    # Total practice sessions
    c.execute('''SELECT COUNT(*) as count FROM practice_sessions
                 WHERE interview_id IN
                 (SELECT id FROM interviews WHERE user_id = ?)''', (user_id,))
    total_sessions = c.fetchone()['count']

    # Average score
    c.execute('''SELECT AVG(score) as avg_score FROM practice_sessions
                 WHERE interview_id IN
                 (SELECT id FROM interviews WHERE user_id = ?)''', (user_id,))
    avg_score = c.fetchone()['avg_score'] or 0

    # Recent interviews
    c.execute('''SELECT * FROM interviews WHERE user_id = ?
                 ORDER BY created_at DESC LIMIT 5''', (user_id,))
    recent_interviews = [dict(row) for row in c.fetchall()]

    conn.close()

    return jsonify({
        'total_interviews': total_interviews,
        'total_sessions': total_sessions,
        'average_score': round(avg_score, 1),
        'recent_interviews': recent_interviews
    })


@app.route('/api/pdf-query', methods=['POST'])
def query_pdf():
    """Query interview materials using PDF Q&A system."""
    data = request.json

    # Log security analysis
    analysis = getattr(g, 'security_analysis', None)
    log_security_event(analysis)

    try:
        graph = create_qa_graph(db_path=INTERVIEW_DB)
        result = graph.process_query(
            query=data['query'],
            retrieve_k=data.get('k', 3),
            include_reasoning=data.get('reasoning', False)
        )
        graph.close()

        if result.get('response'):
            response = result['response']
            return jsonify({
                'success': True,
                'answer': response.answer,
                'sources': [
                    {
                        'page': r.citation,
                        'score': round(r.final_score, 3),
                        'text': r.chunk.text[:100] + '...'
                    }
                    for r in response.sources
                ],
                'reasoning': response.reasoning
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No relevant information found'
            })
    except Exception as e:
        logger.error(f"Error processing PDF query: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'security': 'enabled'
    })


@app.route('/api/security-status', methods=['GET'])
def security_status():
    """Get security middleware status."""
    return jsonify({
        'injection_detection': security_middleware.enable_injection_detection,
        'pii_redaction': security_middleware.enable_pii_redaction,
        'rate_limiting': security_middleware.enable_rate_limiting,
        'output_sanitization': security_middleware.enable_output_sanitization,
        'audit_log': os.path.exists(audit_logger.log_file),
    })


# Error handlers

@app.errorhandler(403)
def forbidden(error):
    """Handle 403 Forbidden."""
    return jsonify({
        'error': 'Access denied due to security policy',
        'status': 403
    }), 403


@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(error):
    logger.error(f"Server error: {error}")
    return jsonify({'error': 'Server error'}), 500


if __name__ == '__main__':
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(logs_dir, exist_ok=True)

    # Initialize database
    init_db()

    print("=" * 70)
    print("Interview Preparation Web Application - SECURE VERSION")
    print("=" * 70)
    print()
    print("✓ Database initialized")
    print("✓ API endpoints ready")
    print("✓ Security guardrails ENABLED")
    print()
    print("Security Features:")
    print("  • Prompt injection detection")
    print("  • PII redaction")
    print("  • Rate limiting (100 req/min, 5000 req/hour)")
    print("  • Output sanitization")
    print("  • Audit logging")
    print()
    print("🚀 Starting server...")
    print()
    print("Open your browser and go to:")
    print("  http://localhost:5000")
    print()
    print("Security logs: logs/security_audit.log")
    print()
    print("=" * 70)

    # Run development server
    app.run(debug=True, port=5000)
