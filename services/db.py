import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.db")

def get_db_connection():
    """Returns a connection to the SQLite database with Row factory enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes the database schema if tables do not exist."""
    logger.info("Initializing SQLite database...")
    with get_db_connection() as conn:
        # Create users table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                github_id TEXT UNIQUE NOT NULL,
                username TEXT NOT NULL,
                avatar_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create builds table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS builds (
                build_id TEXT PRIMARY KEY,
                apk_id TEXT UNIQUE,
                user_id INTEGER,
                source_type TEXT NOT NULL,
                source_value TEXT NOT NULL,
                original_filename TEXT,
                filename TEXT,
                size_bytes INTEGER,
                duration_seconds REAL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
        
        # Add index for speed on user_id
        conn.execute("CREATE INDEX IF NOT EXISTS idx_builds_user_id ON builds(user_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_builds_apk_id ON builds(apk_id);")
        conn.commit()
    logger.info("Database initialized successfully.")

def upsert_user(github_id, username, avatar_url):
    """Inserts or updates a user by their GitHub ID and returns their local user ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (github_id, username, avatar_url)
            VALUES (?, ?, ?)
            ON CONFLICT(github_id) DO UPDATE SET
                username = excluded.username,
                avatar_url = excluded.avatar_url
        """, (str(github_id), username, avatar_url))
        conn.commit()
        
        cursor.execute("SELECT id FROM users WHERE github_id = ?", (str(github_id),))
        row = cursor.fetchone()
        return row["id"] if row else None

def create_build(build_id, user_id, source_type, source_value, original_filename):
    """Creates a new build record with status 'RUNNING'."""
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO builds (build_id, user_id, source_type, source_value, original_filename, status)
            VALUES (?, ?, ?, ?, ?, 'RUNNING')
        """, (build_id, user_id, source_type, source_value, original_filename))
        conn.commit()

def update_build_success(build_id, apk_id, filename, size_bytes, duration_seconds):
    """Updates the build status to success and registers the APK details."""
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE builds
            SET apk_id = ?, filename = ?, size_bytes = ?, duration_seconds = ?, status = ?
            WHERE build_id = ?
        """, (apk_id, filename, size_bytes, duration_seconds, f"SUCCESS:{apk_id}", build_id))
        conn.commit()

def update_build_failed(build_id, error_message):
    """Updates the build status to failed with the error message."""
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE builds
            SET status = ?
            WHERE build_id = ?
        """, (f"FAILED:{error_message}", build_id))
        conn.commit()

def get_build(build_id):
    """Retrieves a single build record by its build_id."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM builds WHERE build_id = ?", (build_id,)).fetchone()
        return dict(row) if row else None

def get_apk_build(apk_id):
    """Retrieves a single build record by its associated apk_id."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM builds WHERE apk_id = ?", (apk_id,)).fetchone()
        return dict(row) if row else None

def get_recent_builds(user_id=None, limit=20):
    """
    Retrieves recent builds. 
    If user_id is provided, retrieves builds for that user.
    If user_id is None, retrieves guest builds (where user_id is NULL).
    """
    with get_db_connection() as conn:
        if user_id is not None:
            rows = conn.execute("""
                SELECT * FROM builds 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (user_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM builds 
                WHERE user_id IS NULL 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(row) for row in rows]

def get_expired_apks(expiration_minutes=30):
    """Retrieves builds with valid apk_ids that are older than the expiration window."""
    with get_db_connection() as conn:
        # SQLite datetime functions expect UTC or local
        # Since created_at is stored in UTC (default CURRENT_TIMESTAMP), 
        # we can query based on time diff.
        rows = conn.execute("""
            SELECT * FROM builds 
            WHERE apk_id IS NOT NULL 
              AND status LIKE 'SUCCESS:%'
              AND datetime(created_at) < datetime('now', ?)
        """, (f"-{expiration_minutes} minutes",)).fetchall()
        return [dict(row) for row in rows]

def expire_apk(apk_id):
    """Marks an APK as expired by nullifying the apk_id and setting status to EXPIRED."""
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE builds 
            SET apk_id = NULL, status = 'EXPIRED'
            WHERE apk_id = ?
        """, (apk_id,))
        conn.commit()

def clear_user_builds(user_id=None):
    """
    Clears builds database entries.
    If user_id is provided, deletes builds for that specific user.
    If user_id is None, deletes guest builds.
    """
    with get_db_connection() as conn:
        if user_id is not None:
            conn.execute("DELETE FROM builds WHERE user_id = ?", (user_id,))
        else:
            conn.execute("DELETE FROM builds WHERE user_id IS NULL")
        conn.commit()
