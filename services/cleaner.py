import os
import logging
import time
import threading
from datetime import datetime, timedelta

from services.db import (
    get_db_connection,
    update_build_success,
    get_apk_build,
    expire_apk,
    get_expired_apks as db_get_expired_apks
)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_apks_dir():
    # Return absolute path to the apks folder relative to this project root
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    apks_dir = os.path.join(base_dir, 'apks')
    os.makedirs(apks_dir, exist_ok=True)
    return apks_dir

def get_metadata_path():
    return os.path.join(get_apks_dir(), 'metadata.json')

def load_metadata():
    """Compatibility helper: returns builds from SQLite in the old metadata format."""
    try:
        conn = get_db_connection()
        rows = conn.execute("SELECT * FROM builds WHERE apk_id IS NOT NULL").fetchall()
        conn.close()
        
        metadata = {}
        for r in rows:
            # Format datetime as ISO string with Z
            created_at_val = r["created_at"]
            if isinstance(created_at_val, str):
                if not created_at_val.endswith('Z'):
                    created_at_val += 'Z'
            else:
                created_at_val = datetime.utcnow().isoformat() + 'Z'
                
            metadata[r["apk_id"]] = {
                "filename": r["filename"],
                "original_name": r["original_filename"],
                "size_bytes": r["size_bytes"],
                "build_duration_seconds": r["duration_seconds"],
                "created_at": created_at_val,
                "status": "success"
            }
        return metadata
    except Exception as e:
        logger.error(f"Error loading compatibility metadata: {e}")
        return {}

def save_metadata(metadata):
    """Compatibility helper: no-op since SQLite handles storage."""
    pass

def add_apk_metadata(build_id, apk_id, filename, original_name, size_bytes, build_duration_seconds):
    """Saves APK metadata into the SQLite builds table by updating the active build record."""
    try:
        update_build_success(build_id, apk_id, filename, size_bytes, build_duration_seconds)
        
        # Print the specific console messages required by the prompt
        print(f"[INFO] APK generated successfully.")
        print(f"[INFO] Scheduled automatic deletion in 30 minutes.")
        logger.info(f"APK {apk_id} ({filename}) registered for build {build_id}. Scheduled deletion in 30 minutes.")
    except Exception as e:
        logger.error(f"Failed to add APK metadata to SQLite: {e}")

def get_apk_metadata(apk_id):
    """Retrieves APK metadata from the SQLite database builds table."""
    try:
        build = get_apk_build(apk_id)
        if not build:
            return None
            
        created_at_val = build["created_at"]
        if isinstance(created_at_val, str):
            if not created_at_val.endswith('Z'):
                created_at_val += 'Z'
        else:
            created_at_val = datetime.utcnow().isoformat() + 'Z'
            
        return {
            "filename": build["filename"],
            "original_name": build["original_filename"],
            "size_bytes": build["size_bytes"],
            "build_duration_seconds": build["duration_seconds"],
            "created_at": created_at_val,
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Failed to get APK metadata for {apk_id}: {e}")
        return None

def delete_apk_file_and_metadata(apk_id, metadata=None):
    """Deletes the physical file and updates the database record to mark the APK as expired."""
    try:
        build = get_apk_build(apk_id)
        if build:
            filename = build.get("filename")
            apks_dir = get_apks_dir()
            file_path = os.path.join(apks_dir, filename)
            
            # Delete physical file
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Removed APK file: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to delete file {file_path}: {e}")
            
            # Update database status to EXPIRED
            expire_apk(apk_id)
            
            # Print the specific console message required by the prompt
            print(f"[INFO] APK deleted automatically after 30 minutes.")
            logger.info(f"APK {apk_id} deleted automatically after 30 minutes.")
            return True
    except Exception as e:
        logger.error(f"Failed to delete APK {apk_id}: {e}")
    return False

def clean_expired_apks():
    """Scan and delete APKs older than 30 minutes using SQLite."""
    try:
        expired_builds = db_get_expired_apks(expiration_minutes=30)
        for build in expired_builds:
            apk_id = build.get("apk_id")
            if apk_id:
                delete_apk_file_and_metadata(apk_id)
    except Exception as e:
        logger.error(f"Error cleaning expired APKs: {e}")

def start_cleanup_scheduler(interval_seconds=60):
    """Start the periodic background cleanup thread."""
    def run_cleanup():
        logger.info("Background APK cleaner thread started.")
        while True:
            try:
                clean_expired_apks()
            except Exception as e:
                logger.error(f"Error in background cleaner loop: {e}")
            time.sleep(interval_seconds)
            
    cleanup_thread = threading.Thread(target=run_cleanup, daemon=True)
    cleanup_thread.start()
    return cleanup_thread
