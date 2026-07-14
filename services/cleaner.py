import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Lock to synchronize access to the metadata JSON file
metadata_lock = threading.Lock()

def get_apks_dir():
    # Return absolute path to the apks folder relative to this project root
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    apks_dir = os.path.join(base_dir, 'apks')
    os.makedirs(apks_dir, exist_ok=True)
    return apks_dir

def get_metadata_path():
    return os.path.join(get_apks_dir(), 'metadata.json')

def load_metadata():
    metadata_path = get_metadata_path()
    with metadata_lock:
        if not os.path.exists(metadata_path):
            return {}
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading metadata file: {e}")
            return {}

def save_metadata(metadata):
    metadata_path = get_metadata_path()
    with metadata_lock:
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=4)
        except Exception as e:
            logger.error(f"Error writing metadata file: {e}")

def add_apk_metadata(apk_id, filename, original_name, size_bytes, build_duration_seconds):
    metadata = load_metadata()
    created_at = datetime.utcnow().isoformat() + 'Z'
    
    metadata[apk_id] = {
        "filename": filename,
        "original_name": original_name,
        "size_bytes": size_bytes,
        "build_duration_seconds": build_duration_seconds,
        "created_at": created_at,
        "status": "success"
    }
    save_metadata(metadata)
    
    # Print the specific console messages required by the prompt
    print(f"[INFO] APK generated successfully.")
    print(f"[INFO] Scheduled automatic deletion in 5 hours.")
    logger.info(f"APK {apk_id} ({filename}) registered. Scheduled deletion in 5 hours.")

def get_apk_metadata(apk_id):
    metadata = load_metadata()
    return metadata.get(apk_id)

def delete_apk_file_and_metadata(apk_id, metadata=None):
    if metadata is None:
        metadata = load_metadata()
    
    if apk_id in metadata:
        info = metadata[apk_id]
        filename = info.get("filename")
        apks_dir = get_apks_dir()
        file_path = os.path.join(apks_dir, filename)
        
        # Delete physical file
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Removed APK file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to delete file {file_path}: {e}")
        
        # Remove from metadata
        del metadata[apk_id]
        save_metadata(metadata)
        
        # Print the specific console message required by the prompt
        print(f"[INFO] APK deleted automatically after 5 hours.")
        logger.info(f"APK {apk_id} deleted automatically after 5 hours.")
        return True
    return False

def clean_expired_apks():
    """Scan and delete APKs older than 5 hours (18000 seconds)."""
    metadata = load_metadata()
    now = datetime.utcnow()
    expired_ids = []
    
    for apk_id, info in list(metadata.items()):
        created_at_str = info.get("created_at")
        if not created_at_str:
            continue
        
        try:
            # Parse ISO timestamp
            created_at = datetime.strptime(created_at_str.replace('Z', ''), "%Y-%m-%dT%H:%M:%S.%f")
            age = now - created_at
            
            if age > timedelta(hours=5):
                expired_ids.append(apk_id)
        except Exception as e:
            logger.error(f"Error parsing created_at for {apk_id}: {e}")
            # If timestamp is corrupted, flag for deletion just in case to be safe
            expired_ids.append(apk_id)
            
    for apk_id in expired_ids:
        delete_apk_file_and_metadata(apk_id, metadata)

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
