import os
import uuid
import threading
import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, send_from_directory, current_app
from werkzeug.utils import secure_filename

from services.project_manager import clone_repo, extract_zip, cleanup_directory
from services.cleaner import get_apk_metadata, get_apks_dir
from builders.gradle_builder import build_project

logger = logging.getLogger(__name__)

main_bp = Blueprint('main', __name__)

# In-memory backup for running threads (to prevent garbage collection or to query active builds)
active_threads = {}

def get_logs_dir():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs_dir = os.path.join(base_dir, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir

def get_uploads_dir():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    uploads_dir = os.path.join(base_dir, 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    return uploads_dir

def get_temp_dir():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_dir = os.path.join(base_dir, 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def write_status(build_id, status_str):
    status_file = os.path.join(get_logs_dir(), f"{build_id}.status")
    try:
        with open(status_file, "w", encoding="utf-8") as f:
            f.write(status_str)
    except Exception as e:
        logger.error(f"Failed to write status for build {build_id}: {e}")

def read_status(build_id):
    status_file = os.path.join(get_logs_dir(), f"{build_id}.status")
    if not os.path.exists(status_file):
        return "UNKNOWN"
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logger.error(f"Failed to read status for build {build_id}: {e}")
        return "UNKNOWN"

def get_build_start_time(build_id):
    log_path = os.path.join(get_logs_dir(), f"{build_id}.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                first_line = f.readline() # --- APK BUILD LOGS ...
                second_line = f.readline() # Timestamp: ...
                if second_line.startswith("Timestamp: "):
                    ts_str = second_line.split("Timestamp: ", 1)[1].strip()
                    if ts_str.endswith("Z"):
                        ts_str = ts_str[:-1]
                    if "." in ts_str:
                        return datetime.fromisoformat(ts_str)
                    else:
                        return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
        except Exception as e:
            logger.error(f"Failed to parse timestamp from log for {build_id}: {e}")
            
    # Fallback to st_ctime or st_mtime
    try:
        stat = os.stat(log_path)
        return datetime.fromtimestamp(getattr(stat, 'st_birthtime', stat.st_mtime))
    except Exception:
        return datetime.utcnow()

def build_worker(build_id, source_type, source_value, original_filename):
    """
    Background worker thread running the clone/extraction and Gradle compilation.
    """
    write_status(build_id, "RUNNING")
    
    log_file_path = os.path.join(get_logs_dir(), f"{build_id}.log")
    temp_working_dir = os.path.join(get_temp_dir(), build_id)
    os.makedirs(temp_working_dir, exist_ok=True)
    
    uploaded_zip_path = None
    if source_type == "zip":
        uploaded_zip_path = source_value
    elif source_type == "url_zip":
        uploaded_zip_path = os.path.join(get_uploads_dir(), f"{build_id}_downloaded.zip")
    
    try:
        # Step 1: Clone or extract project
        from builders.gradle_builder import canceled_builds
        if source_type == "git":
            clone_repo(source_value, temp_working_dir, log_file_path)
            if build_id in canceled_builds:
                raise RuntimeError("Build was cancelled by the user.")
        elif source_type == "url_zip":
            from services.project_manager import download_zip_from_url
            download_zip_from_url(source_value, uploaded_zip_path, log_file_path)
            if build_id in canceled_builds:
                raise RuntimeError("Build was cancelled by the user.")
            extract_zip(uploaded_zip_path, temp_working_dir, log_file_path)
            if build_id in canceled_builds:
                raise RuntimeError("Build was cancelled by the user.")
        elif source_type == "zip":
            extract_zip(source_value, temp_working_dir, log_file_path)
            if build_id in canceled_builds:
                raise RuntimeError("Build was cancelled by the user.")
            
        # Step 2: Run Gradle Build
        result = build_project(temp_working_dir, build_id, log_file_path, original_filename)
        
        # Step 3: Record success
        apk_id = result["apk_id"]
        write_status(build_id, f"SUCCESS:{apk_id}")
        
    except Exception as e:
        logger.error(f"Build worker {build_id} failed: {e}")
        # Append error directly to build logs for user visibility
        try:
            with open(log_file_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n[ERROR] Build pipeline interrupted: {str(e)}\n")
                lf.write("BUILD FAILED\n")
        except Exception as le:
            logger.error(f"Could not append error to log: {le}")
            
        write_status(build_id, f"FAILED:{str(e)}")
        
    finally:
        # Step 4: Cleanup source ZIP from uploads folder if it exists
        if uploaded_zip_path and os.path.exists(uploaded_zip_path):
            try:
                os.remove(uploaded_zip_path)
            except Exception as e:
                logger.error(f"Failed to delete uploaded ZIP {uploaded_zip_path}: {e}")
        
        # Ensure working directory is cleaned up in case builder didn't finish it
        if os.path.exists(temp_working_dir):
            cleanup_directory(temp_working_dir)
            
        # Remove from active threads list
        active_threads.pop(build_id, None)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/build', methods=['POST'])
def trigger_build():
    build_id = str(uuid.uuid4())
    log_file_path = os.path.join(get_logs_dir(), f"{build_id}.log")
    
    # Initialize log file
    try:
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(f"--- APK BUILD LOGS (Build ID: {build_id}) ---\n")
            f.write(f"Timestamp: {datetime.utcnow().isoformat()}Z\n\n")
    except Exception as e:
        return jsonify({"error": f"Failed to initialize build logs: {str(e)}"}), 500
        
    build_type = request.form.get("type")
    
    if build_type == "git":
        git_url = request.form.get("git_url")
        if not git_url:
            return jsonify({"error": "Git or Project URL is required"}), 400
        
        # Validate URL
        from services.project_manager import validate_project_url
        if not validate_project_url(git_url):
            return jsonify({"error": "Invalid or insecure project URL. Must be a valid Git or ai.studio link."}), 400
            
        # Determine if we should clone (Git) or download (ZIP/ai.studio)
        import urllib.parse
        parsed_url = urllib.parse.urlparse(git_url.strip())
        domain = parsed_url.netloc.lower()
        is_git_repo = "github.com" in domain or "gitlab.com" in domain or "bitbucket.org" in domain or parsed_url.path.endswith(".git")
        
        if is_git_repo:
            build_type_worker = "git"
        else:
            build_type_worker = "url_zip"
            
        # Derive original filename from git URL for apk naming
        original_filename = git_url.split('/')[-1]
        if original_filename.endswith('.git'):
            original_filename = original_filename[:-4]
        if not original_filename:
            original_filename = "project"
            
        source_val = git_url
        
    elif build_type == "zip":
        if 'zip_file' not in request.files:
            return jsonify({"error": "No ZIP file uploaded"}), 400
            
        file = request.files['zip_file']
        if file.filename == '':
            return jsonify({"error": "Selected file is empty"}), 400
            
        if not file.filename.lower().endswith('.zip'):
            return jsonify({"error": "Only ZIP files are supported"}), 400
            
        filename = secure_filename(file.filename)
        upload_path = os.path.join(get_uploads_dir(), f"{build_id}_{filename}")
        
        try:
            file.save(upload_path)
        except Exception as e:
            return jsonify({"error": f"Failed to save uploaded file: {str(e)}"}), 500
            
        original_filename = filename
        source_val = upload_path
        build_type_worker = "zip"
        
    else:
        return jsonify({"error": "Invalid build source type"}), 400
        
    # Start the worker thread
    from builders.gradle_builder import active_processes
    active_processes[build_id] = "STARTING"
    
    t = threading.Thread(
        target=build_worker,
        args=(build_id, build_type_worker, source_val, original_filename),
        daemon=True
    )
    active_threads[build_id] = t
    t.start()
    
    return jsonify({
        "status": "started",
        "build_id": build_id
    })

@main_bp.route('/build-status/<build_id>', methods=['GET'])
def check_build_status(build_id):
    status_raw = read_status(build_id)
    
    if status_raw == "RUNNING" and build_id not in active_threads:
        status_raw = "FAILED: Build pipeline was interrupted."
        write_status(build_id, status_raw)
        
    if status_raw == "RUNNING":
        return jsonify({"status": "running"})
    elif status_raw.startswith("SUCCESS:"):
        apk_id = status_raw.split(":", 1)[1]
        metadata = get_apk_metadata(apk_id)
        if not metadata:
            return jsonify({"status": "expired", "error": "This APK has expired and has been removed from the server."})
            
        return jsonify({
            "status": "success",
            "apk_id": apk_id,
            "filename": metadata["filename"],
            "size_bytes": metadata["size_bytes"],
            "duration_seconds": metadata["build_duration_seconds"]
        })
    elif status_raw.startswith("FAILED:"):
        err = status_raw.split(":", 1)[1]
        return jsonify({"status": "failed", "error": err})
    else:
        return jsonify({"status": "unknown"})

@main_bp.route('/download/<apk_id>', methods=['GET'])
def download_apk(apk_id):
    metadata = get_apk_metadata(apk_id)
    
    if not metadata:
        # Return exact error message as required by the prompt
        return render_template(
            'error.html',
            message="This APK has expired and has been removed from the server. Please build the project again to generate a new APK."
        ), 410
        
    apks_dir = get_apks_dir()
    filename = metadata["filename"]
    original_name = metadata.get("original_name", "app-debug.apk")
    
    # Ensure standard APK extension for download name
    if not original_name.lower().endswith('.apk'):
        original_name = os.path.splitext(original_name)[0] + ".apk"
        
    file_path = os.path.join(apks_dir, filename)
    
    if not os.path.exists(file_path):
        return render_template(
            'error.html',
            message="This APK has expired and has been removed from the server. Please build the project again to generate a new APK."
        ), 410
        
    return send_from_directory(
        directory=apks_dir,
        path=filename,
        as_attachment=True,
        download_name=original_name
    )

@main_bp.route('/dev/logs')
def dev_logs():
    import glob
    logs_dir = get_logs_dir()
    log_files = glob.glob(os.path.join(logs_dir, "*.log"))
    
    builds = []
    for file_path in log_files:
        filename = os.path.basename(file_path)
        build_id = os.path.splitext(filename)[0]
        
        stat = os.stat(file_path)
        # Convert modification time to readable string
        modified_time = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        status = read_status(build_id)
        
        builds.append({
            "build_id": build_id,
            "modified_at": modified_time,
            "status": status
        })
        
    # Sort builds by time descending
    builds.sort(key=lambda x: x["modified_at"], reverse=True)
    
    success_count = sum(1 for b in builds if b["status"].startswith("SUCCESS"))
    failed_count = sum(1 for b in builds if b["status"].startswith("FAILED"))
    running_count = sum(1 for b in builds if b["status"] == "RUNNING")
    
    return render_template(
        'dev_logs.html', 
        builds=builds, 
        success_count=success_count, 
        failed_count=failed_count, 
        running_count=running_count
    )

@main_bp.route('/dev/logs/<build_id>')
def dev_log_view(build_id):
    log_path = os.path.join(get_logs_dir(), f"{build_id}.log")
    if not os.path.exists(log_path):
        return "Log file not found", 404
        
    status = read_status(build_id)
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        content = f"Error reading log file: {e}"
        
    return render_template('dev_log_view.html', build_id=build_id, status=status, content=content)

@main_bp.route('/dev/logs/clear', methods=['POST'])
def dev_logs_clear():
    import glob
    logs_dir = get_logs_dir()
    log_files = glob.glob(os.path.join(logs_dir, "*.log"))
    status_files = glob.glob(os.path.join(logs_dir, "*.status"))
    
    for file_path in log_files + status_files:
        try:
            os.remove(file_path)
        except Exception as e:
            logger.error(f"Failed to delete developer log file {file_path}: {e}")
            
    # Redirect back to logs dashboard
    from flask import redirect, url_for
    return redirect(url_for('main.dev_logs'))

@main_bp.route('/recent-builds')
def get_recent_builds():
    from datetime import datetime, timedelta
    from services.cleaner import load_metadata
    import glob
    metadata = load_metadata()
    now = datetime.utcnow()
    
    active_builds = []
    
    # 1. Fetch running and failed builds from log files
    logs_dir = get_logs_dir()
    log_files = glob.glob(os.path.join(logs_dir, "*.log"))
    
    for file_path in log_files:
        filename = os.path.basename(file_path)
        build_id = os.path.splitext(filename)[0]
        status = read_status(build_id)
        
        if status == "RUNNING" and build_id not in active_threads:
            status = "FAILED: Build pipeline was interrupted."
            write_status(build_id, status)
            
        created_at = get_build_start_time(build_id)
        
        if status == "RUNNING" or status.startswith("FAILED:"):
            age = now - created_at
            max_age = timedelta(hours=5)
            if age < max_age:
                active_builds.append({
                    "build_id": build_id,
                    "status": "running" if status == "RUNNING" else "failed",
                    "original_name": f"App Project (Build {build_id[:6]})",
                    "created_at": created_at.isoformat() + "Z",
                    "time_remaining": "Currently Compiling..." if status == "RUNNING" else "Build Failed"
                })

    # 2. Fetch successful completed builds from metadata
    for apk_id, info in metadata.items():
        try:
            created_at_str = info.get("created_at")
            created_at = datetime.strptime(created_at_str.replace('Z', ''), "%Y-%m-%dT%H:%M:%S.%f")
            age = now - created_at
            
            max_age = timedelta(hours=5)
            if age < max_age:
                remaining = max_age - age
                hours_rem = int(remaining.total_seconds() // 3600)
                mins_rem = int((remaining.total_seconds() % 3600) // 60)
                time_remaining_str = f"{hours_rem}h {mins_rem}m remaining"
                
                # Check if file actually exists
                apks_dir = get_apks_dir()
                file_path = os.path.join(apks_dir, info["filename"])
                if os.path.exists(file_path):
                    active_builds.append({
                        "status": "success",
                        "apk_id": apk_id,
                        "original_name": info.get("original_name", "App Project"),
                        "filename": info["filename"],
                        "size_bytes": info["size_bytes"],
                        "duration_seconds": info.get("build_duration_seconds", 0),
                        "created_at": created_at_str,
                        "time_remaining": time_remaining_str
                    })
        except Exception as e:
            logger.error(f"Error parsing recent build {apk_id}: {e}")
            
    # Sort by created time descending
    active_builds.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify(active_builds)

@main_bp.route('/clear-all-data', methods=['POST'])
def clear_all_data():
    # 1. Clear apks metadata and files
    from services.cleaner import get_metadata_path, save_metadata
    apks_dir = get_apks_dir()
    for f in os.listdir(apks_dir):
        if f != 'metadata.json':
            try:
                os.remove(os.path.join(apks_dir, f))
            except Exception:
                pass
    save_metadata({}) # Reset metadata
    
    # 2. Clear logs
    logs_dir = get_logs_dir()
    for f in os.listdir(logs_dir):
        try:
            os.remove(os.path.join(logs_dir, f))
        except Exception:
            pass
            
    # 3. Clear uploads
    uploads_dir = get_uploads_dir()
    for f in os.listdir(uploads_dir):
        try:
            os.remove(os.path.join(uploads_dir, f))
        except Exception:
            pass
            
    # 4. Clear temp
    temp_dir = get_temp_dir()
    for f in os.listdir(temp_dir):
        path = os.path.join(temp_dir, f)
        try:
            if os.path.isdir(path):
                cleanup_directory(path)
            else:
                os.remove(path)
        except Exception:
            pass
            
    return jsonify({"status": "success", "message": "All local data has been successfully cleared from the server."})

@main_bp.route('/latest-update')
def get_latest_update():
    import subprocess
    try:
        # Get the latest commit hash, message, and relative time
        # Format: Hash|Message|Time
        result = subprocess.run(
            ['git', 'log', '-1', '--pretty=format:%h|%s|%ar'],
            capture_output=True,
            text=True,
            check=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        parts = result.stdout.strip().split('|', 2)
        if len(parts) == 3:
            return jsonify({
                "status": "success",
                "hash": parts[0],
                "message": parts[1],
                "time": parts[2]
            })
        return jsonify({"status": "error", "message": "Could not parse git log"})
    except Exception as e:
        logger.error(f"Failed to fetch git commit: {e}")
        return jsonify({"status": "error", "message": "Git is not initialized or an error occurred."})

@main_bp.route('/cancel-build/<build_id>', methods=['POST'])
def cancel_build_route(build_id):
    from builders.gradle_builder import cancel_build, active_processes
    if cancel_build(build_id):
        # We manually write the status to FAILED here to immediately update the frontend
        write_status(build_id, "FAILED: Build was cancelled by the user.")
        active_processes.pop(build_id, None)
        return jsonify({"status": "success", "message": "Build terminated successfully."})
    return jsonify({"status": "error", "message": "Build not running or not found."}), 404
