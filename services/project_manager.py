import os
import shutil
import urllib.parse
import urllib.request
import zipfile
import subprocess
import re
import stat
import logging

logger = logging.getLogger(__name__)

def validate_project_url(url):
    """
    Validates if the provided string is a valid HTTPS Git repository URL,
    an ai.studio sharing link, or a direct ZIP download link.
    """
    if not url:
        return False
    
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    
    # Only allow http/https
    if parsed.scheme not in ('http', 'https'):
        return False
        
    if not parsed.netloc:
        return False
        
    # Ensure there are no spaces or command-injection-like characters in the URL
    if any(char in url for char in (' ', ';', '&', '|', '$', '`', '<', '>', '\n', '\r')):
        return False
        
    # Check domains
    domain = parsed.netloc.lower()
    
    # Check for git domains or extension
    is_git = "github.com" in domain or "gitlab.com" in domain or "bitbucket.org" in domain or parsed.path.endswith(".git")
    
    # Check for ai.studio links or zip files
    is_ai_studio = "ai.studio" in domain and "/apps/" in parsed.path
    is_zip_url = parsed.path.lower().endswith(".zip")
    
    return is_git or is_ai_studio or is_zip_url

def download_zip_from_url(url, target_zip_path, log_file_path):
    """
    Downloads a project ZIP file from a URL. Logs progress to log_file_path.
    """
    with open(log_file_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n[SYSTEM] Fetching project archive from URL: {url}...\n")
        log_file.flush()
        
        try:
            # Configure request with User-Agent to prevent bot-detection issues
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            
            with urllib.request.urlopen(req, timeout=180) as response:
                with open(target_zip_path, 'wb') as out_file:
                    out_file.write(response.read())
                    
            log_file.write("[SYSTEM] Download completed successfully.\n")
            return True
        except Exception as e:
            log_file.write(f"[ERROR] Failed to download project file: {e}\n")
            raise RuntimeError(f"HTTP download failed: {e}") from e

def clone_repo(repo_url, target_dir, log_file_path):
    """
    Clones a Git repository into target_dir. Logs stdout/stderr to log_file_path.
    Runs subprocess without shell=True to protect against command injection.
    """
    repo_url = repo_url.strip()
    if not validate_project_url(repo_url):
        raise ValueError("Invalid or unsupported Git repository URL.")
        
    # Run git clone with depth=1 for speed
    cmd = ["git", "clone", "--depth", "1", repo_url, target_dir]
    
    with open(log_file_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n[SYSTEM] Cloning repository: {repo_url}...\n")
        log_file.flush()
        
        try:
            process = subprocess.run(
                cmd,
                stdout=log_file,
                stderr=log_file,
                text=True,
                check=True,
                timeout=300  # 5 minutes timeout
            )
            log_file.write("[SYSTEM] Repository cloned successfully.\n")
            return True
        except subprocess.TimeoutExpired as te:
            log_file.write(f"[ERROR] Cloning repository timed out after 5 minutes.\n")
            raise RuntimeError("Repository clone timed out.") from te
        except subprocess.CalledProcessError as cpe:
            log_file.write(f"[ERROR] Git clone failed with exit code {cpe.returncode}.\n")
            raise RuntimeError(f"Git clone failed (exit code {cpe.returncode}).") from cpe
        except Exception as e:
            log_file.write(f"[ERROR] Failed to execute git clone: {e}\n")
            raise RuntimeError(f"Cloning failed: {e}") from e

def extract_zip(zip_path, target_dir, log_file_path):
    """
    Safely extracts a ZIP file to target_dir. Mitigates Zip Slip (Path Traversal).
    """
    with open(log_file_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n[SYSTEM] Extracting uploaded project ZIP...\n")
        log_file.flush()
        
        try:
            target_dir_abs = os.path.abspath(target_dir)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Check for Zip Slip
                for member in zip_ref.infolist():
                    # Calculate target path for member
                    member_path_abs = os.path.abspath(os.path.join(target_dir_abs, member.filename))
                    # Ensure it's inside target directory
                    if not member_path_abs.startswith(target_dir_abs):
                        raise PermissionError(f"Security Warning: Path traversal detected in ZIP member: {member.filename}")
                
                # Perform extraction
                zip_ref.extractall(target_dir_abs)
                
            log_file.write("[SYSTEM] Extraction completed successfully.\n")
            return True
        except PermissionError as pe:
            log_file.write(f"[ERROR] Security Exception: {pe}\n")
            raise pe
        except Exception as e:
            log_file.write(f"[ERROR] Failed to extract ZIP file: {e}\n")
            raise RuntimeError(f"ZIP extraction failed: {e}") from e

def handle_remove_readonly(func, path, exc):
    """
    Error handler for shutil.rmtree to remove read-only files (common in .git folders).
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        logger.warning(f"Could not change permissions or remove path {path}: {e}")

def cleanup_directory(path):
    """
    Safely deletes a directory and its contents recursively.
    """
    if os.path.exists(path):
        try:
            shutil.rmtree(path, onerror=handle_remove_readonly)
        except Exception as e:
            logger.error(f"Failed to clean up directory {path}: {e}")
