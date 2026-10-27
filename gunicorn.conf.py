"""
Gunicorn configuration for production deployment (Render, Railway, Linux, Cloud Run).
Automatically detects Render's dynamically assigned $PORT.
"""
import os

# Render automatically assigns the PORT environment variable (e.g. 10000)
port = os.environ.get("PORT", "5000")
bind = f"0.0.0.0:{port}"

# Concurrency tuning
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("PYTHON_THREADS", "4"))
timeout = 120

# Stream logs directly to stdout/stderr for Render log aggregation
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
