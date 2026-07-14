import os
import sys
import subprocess
import time
import uuid
import glob
import shutil
import logging
import re
from datetime import datetime
from services.project_manager import cleanup_directory
from services.cleaner import add_apk_metadata

logger = logging.getLogger(__name__)

active_processes = {}
canceled_builds = set()

def cancel_build(build_id):
    """Forcefully terminates an ongoing build."""
    canceled_builds.add(build_id)
    if build_id in active_processes:
        process = active_processes.get(build_id)
        if hasattr(process, 'poll') and process.poll() is None:
            try:
                import sys
                import subprocess
                if sys.platform.startswith('win'):
                    # Use taskkill /F /T /PID to kill the entire process tree on Windows
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True)
                else:
                    process.terminate()
            except Exception as e:
                logger.error(f"Failed to terminate process for {build_id}: {e}")
        return True
    return False

def heal_google_services(project_root, log_file):
    """
    Scans for Firebase Google Services plugin applications and injects a dummy google-services.json if missing.
    """
    has_google_services = False
    package_name = "com.example.app"
    
    # 1. Scan for google-services plugin and package name
    for root, dirs, files in os.walk(project_root):
        for file in files:
            if file in ("build.gradle", "build.gradle.kts"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                        if "google-services" in content or "gms.google-services" in content:
                            has_google_services = True
                        
                        # Find namespace or applicationId
                        ns_match = re.search(r'namespace\s*=?\s*["\']([^"\']+)["\']', content)
                        if ns_match:
                            package_name = ns_match.group(1)
                        else:
                            app_match = re.search(r'applicationId\s*=?\s*["\']([^"\']+)["\']', content)
                            if app_match:
                                package_name = app_match.group(1)
                except Exception:
                    pass

    # 2. Inject dummy google-services.json if required and missing
    if has_google_services:
        app_dir = os.path.join(project_root, "app")
        target_dir = app_dir if os.path.exists(app_dir) else project_root
        json_path = os.path.join(target_dir, "google-services.json")
        
        if not os.path.exists(json_path):
            log_file.write(f"[SYSTEM] Google Services plugin detected but google-services.json is missing. Injecting dummy json for package: {package_name}...\n")
            dummy_json = f"""{{
  "project_info": {{
    "project_number": "1234567890",
    "project_id": "dummy-project",
    "storage_bucket": "dummy-project.appspot.com"
  }},
  "client": [
    {{
      "client_info": {{
        "mobilesdk_app_id": "1:1234567890:android:abc123def456",
        "android_client_info": {{
          "package_name": "{package_name}"
        }}
      }},
      "api_key": [
        {{
          "current_key": "dummy_api_key_for_compilation_only"
        }}
      ],
      "services": {{
        "appinvite_service": {{
          "other_platform_oauth_client": []
        }}
      }}
    }}
  ],
  "configuration_version": "1"
}}"""
            try:
                with open(json_path, "w", encoding="utf-8") as f:
                    f.write(dummy_json)
                log_file.write("[SYSTEM] Injected dummy google-services.json successfully.\n")
            except Exception as e:
                log_file.write(f"[WARNING] Failed to write dummy google-services.json: {e}\n")
            log_file.flush()

def heal_gradle_properties(project_root, log_file):
    """
    Ensures that gradle.properties is configured with optimized memory settings
    to prevent JVM OutOfMemory errors during heavy Dex compiling.
    """
    props_path = os.path.join(project_root, "gradle.properties")
    lines_to_add = [
        "org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m -XX:+UseG1GC",
        "org.gradle.daemon=false"
    ]
    
    existing_content = ""
    if os.path.exists(props_path):
        try:
            with open(props_path, "r", encoding="utf-8", errors="replace") as f:
                existing_content = f.read()
        except Exception:
            pass
            
    needs_update = False
    mode = "a" if os.path.exists(props_path) else "w"
    
    try:
        with open(props_path, mode, encoding="utf-8") as f:
            if mode == "w":
                log_file.write("[SYSTEM] Creating gradle.properties with memory optimizations...\n")
                f.write("\n".join(lines_to_add) + "\n")
            else:
                if "org.gradle.jvmargs" not in existing_content:
                    f.write("\norg.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m -XX:+UseG1GC\n")
                    needs_update = True
                if "org.gradle.daemon" not in existing_content:
                    f.write("\norg.gradle.daemon=false\n")
                    needs_update = True
                    
                if needs_update:
                    log_file.write("[SYSTEM] Appended JVM memory optimization arguments to gradle.properties.\n")
        log_file.flush()
    except Exception as e:
        log_file.write(f"[WARNING] Failed to heal gradle.properties: {e}\n")
        log_file.flush()

def heal_missing_sdk_components(log_content, log_file, sdk_path):
    """
    Parses build logs for missing platforms or build tools, and runs sdkmanager to install them.
    Returns True if a component was installed, prompting a retry.
    """
    if not sdk_path:
        return False
        
    is_windows = sys.platform.startswith('win')
    sdkmanager_exe = "sdkmanager.bat" if is_windows else "sdkmanager"
    sdkmanager_path = os.path.join(sdk_path, "cmdline-tools", "latest", "bin", sdkmanager_exe)
    if not os.path.exists(sdkmanager_path):
        guesses = glob.glob(os.path.join(sdk_path, "cmdline-tools", "*", "bin", sdkmanager_exe))
        if guesses:
            sdkmanager_path = guesses[0]
        else:
            sdkmanager_path = sdkmanager_exe # Fallback to Path
            
    installed_anything = False
    
    # 1. Parse missing Build Tools
    bt_match = re.search(r"Failed to find Build Tools revision (\d+\.\d+\.\d+)", log_content)
    if bt_match:
        bt_version = bt_match.group(1)
        log_file.write(f"\n[SYSTEM] Missing Build Tools {bt_version} detected. Attempting automatic installation...\n")
        log_file.flush()
        cmd = [sdkmanager_path, f"build-tools;{bt_version}"]
        if is_windows and sdkmanager_path == sdkmanager_exe:
            cmd = ["cmd.exe", "/c", sdkmanager_exe, f"build-tools;{bt_version}"]
        elif is_windows and os.path.exists(sdkmanager_path):
            cmd = ["cmd.exe", "/c", sdkmanager_path, f"build-tools;{bt_version}"]
            
        try:
            # We must auto-respond "y" to key license prompts
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log_file, stderr=log_file, text=True)
            process.communicate(input="y\ny\ny\ny\n")
            if process.returncode == 0:
                log_file.write(f"[SYSTEM] Build Tools {bt_version} installed successfully.\n")
                installed_anything = True
            else:
                log_file.write(f"[WARNING] sdkmanager exited with code {process.returncode}.\n")
        except Exception as e:
            log_file.write(f"[WARNING] Failed to install build tools via sdkmanager: {e}\n")
        log_file.flush()
        
    # 2. Parse missing SDK Platform
    plat_match = re.search(r"Failed to find target with hash string 'android-(\d+)'", log_content)
    if not plat_match:
        plat_match = re.search(r"platforms;android-(\d+) not found", log_content)
        
    if plat_match:
        api_level = plat_match.group(1)
        log_file.write(f"\n[SYSTEM] Missing SDK Platform API {api_level} detected. Attempting automatic installation...\n")
        log_file.flush()
        cmd = [sdkmanager_path, f"platforms;android-{api_level}"]
        if is_windows and sdkmanager_path == sdkmanager_exe:
            cmd = ["cmd.exe", "/c", sdkmanager_exe, f"platforms;android-{api_level}"]
        elif is_windows and os.path.exists(sdkmanager_path):
            cmd = ["cmd.exe", "/c", sdkmanager_path, f"platforms;android-{api_level}"]
            
        try:
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log_file, stderr=log_file, text=True)
            process.communicate(input="y\ny\ny\ny\n")
            if process.returncode == 0:
                log_file.write(f"[SYSTEM] SDK Platform API {api_level} installed successfully.\n")
                installed_anything = True
            else:
                log_file.write(f"[WARNING] sdkmanager exited with code {process.returncode}.\n")
        except Exception as e:
            log_file.write(f"[WARNING] Failed to install platform via sdkmanager: {e}\n")
        log_file.flush()
        
    return installed_anything

def find_project_root(start_dir):
    """
    Recursively searches for settings.gradle or settings.gradle.kts to locate the Android project root.
    Searches up to depth 3.
    """
    for root, dirs, files in os.walk(start_dir):
        # Calculate current depth relative to start_dir
        rel_path = os.path.relpath(root, start_dir)
        depth = 0 if rel_path == '.' else len(rel_path.split(os.sep))
        if depth > 3:
            continue
            
        if "settings.gradle" in files or "settings.gradle.kts" in files:
            return root
            
    return None

def find_apks(project_root):
    """
    Searches for generated APKs in the project root build output directory.
    Prioritizes debug builds and filters out unaligned/intermediate APKs.
    """
    apk_paths = []
    # Search for APKs recursively inside project_root
    search_pattern = os.path.join(project_root, "**", "*.apk")
    for path in glob.glob(search_pattern, recursive=True):
        filename = os.path.basename(path).lower()
        # Filter out intermediate build files
        if "unaligned" not in filename and "unsigned" not in filename and "intermediates" not in path:
            apk_paths.append(path)
            
    # Sort: put debug APKs first
    apk_paths.sort(key=lambda x: "debug" in x.lower(), reverse=True)
    return apk_paths

def build_project(temp_dir, build_id, log_file_path, original_filename="project"):
    """
    Finds the Android project, configures local.properties, runs gradlew assembleDebug,
    automatically copies the generated APK, logs output, and cleans up the temp dir.
    """
    start_time = time.time()
    project_root = None
    
    try:
        with open(log_file_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"[SYSTEM] Starting build for ID: {build_id}\n")
            log_file.flush()
            
            if build_id in canceled_builds:
                log_file.write("\nBUILD FAILED\n")
                log_file.write("Reason: Build was cancelled by the user.\n")
                log_file.flush()
                raise RuntimeError("Build was cancelled by the user.")
            
            # 1. Find project root
            project_root = find_project_root(temp_dir)
            if not project_root:
                log_file.write("[ERROR] Could not find settings.gradle or settings.gradle.kts in the project.\n")
                log_file.write("BUILD FAILED\n")
                raise RuntimeError("Android Gradle project structure not found (missing settings.gradle).")
                
            log_file.write(f"[SYSTEM] Detected Android project root at: {project_root}\n")
            log_file.flush()
            
            # 2. Setup local.properties with Android SDK path
            sdk_path = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
            if not sdk_path:
                # Common fallback locations on Linux/Ubuntu and Windows
                guesses = [
                    "/usr/lib/android-sdk",
                    "/home/ubuntu/Android/Sdk",
                    "/var/lib/android-sdk",
                    os.path.expanduser("~/Android/Sdk"),
                    # Windows default installation paths
                    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk") if os.environ.get("LOCALAPPDATA") else None,
                    os.path.expanduser("~/AppData/Local/Android/Sdk")
                ]
                for guess in guesses:
                    if guess and os.path.exists(guess):
                        sdk_path = guess
                        break
                        
            if sdk_path:
                # Normalize path for local.properties (forward slashes are required even on Windows)
                normalized_sdk = sdk_path.replace("\\", "/")
                local_props_path = os.path.join(project_root, "local.properties")
                try:
                    with open(local_props_path, "w", encoding="utf-8") as lp:
                        lp.write(f"sdk.dir={normalized_sdk}\n")
                    log_file.write(f"[SYSTEM] Created local.properties with sdk.dir={normalized_sdk}\n")
                except Exception as e:
                    log_file.write(f"[WARNING] Could not write local.properties: {e}\n")
            else:
                log_file.write("[WARNING] ANDROID_HOME or ANDROID_SDK_ROOT is not defined. local.properties was not generated. Build may fail if Android SDK is not in default locations.\n")
            log_file.flush()
            
            # Generate a debug.keystore if missing in the project root
            is_windows = sys.platform.startswith('win')
            keystore_path = os.path.join(project_root, "debug.keystore")
            if not os.path.exists(keystore_path):
                log_file.write("[SYSTEM] debug.keystore not found. Generating a temporary debug keystore...\n")
                log_file.flush()
                
                keytool_exe = "keytool.exe" if is_windows else "keytool"
                java_home = os.environ.get("JAVA_HOME")
                if java_home:
                    keytool_abs = os.path.join(java_home, "bin", keytool_exe)
                    if os.path.exists(keytool_abs):
                        keytool_exe = keytool_abs
                        
                keytool_cmd = [
                    keytool_exe, "-genkey", "-v", 
                    "-keystore", keystore_path, 
                    "-storepass", "android", 
                    "-alias", "androiddebugkey", 
                    "-keypass", "android", 
                    "-keyalg", "RSA", 
                    "-keysize", "2048", 
                    "-validity", "10000", 
                    "-dname", "CN=Android Debug,O=Android,C=US"
                ]
                
                try:
                    subprocess.run(keytool_cmd, check=True, stdout=log_file, stderr=log_file, timeout=45)
                    log_file.write("[SYSTEM] debug.keystore generated successfully.\n")
                except Exception as e:
                    log_file.write(f"[WARNING] Failed to generate debug.keystore: {e}\n")
                log_file.flush()
            
            # 3. Determine gradlew command based on OS and availability
            gradlew_file = "gradlew.bat" if is_windows else "gradlew"
            gradlew_path = os.path.join(project_root, gradlew_file)
            
            if os.path.exists(gradlew_path):
                if is_windows:
                    # Windows: execute .bat file safely using cmd /c
                    cmd = ["cmd.exe", "/c", gradlew_path, "assembleDebug"]
                else:
                    # Linux: set execute permissions and run via /bin/sh
                    try:
                        os.chmod(gradlew_path, os.stat(gradlew_path).st_mode | 0o111)
                        log_file.write("[SYSTEM] Made gradlew script executable.\n")
                    except Exception as e:
                        log_file.write(f"[WARNING] Failed to chmod +x gradlew: {e}\n")
                    cmd = ["/bin/sh", gradlew_path, "assembleDebug"]
            else:
                log_file.write("[WARNING] gradlew script not found in project root. Attempting fallback to global 'gradle' command...\n")
                if is_windows:
                    cmd = ["cmd.exe", "/c", "gradle", "assembleDebug"]
                else:
                    cmd = ["gradle", "assembleDebug"]
                
            # Run google-services check and auto-heal
            heal_google_services(project_root, log_file)
            heal_gradle_properties(project_root, log_file)
            
            # Prepare environment
            env = os.environ.copy()
            if sdk_path:
                env["ANDROID_HOME"] = sdk_path
                env["ANDROID_SDK_ROOT"] = sdk_path
                
            # Stop any stale background Gradle daemons to free up RAM before starting compilation
            try:
                stop_cmd = ["cmd.exe", "/c", gradlew_path, "--stop"] if is_windows else ["/bin/sh", gradlew_path, "--stop"]
                if not os.path.exists(gradlew_path):
                    stop_cmd = ["cmd.exe", "/c", "gradle", "--stop"] if is_windows else ["gradle", "--stop"]
                
                log_file.write("[SYSTEM] Cleaning up stale background Gradle Daemons to reclaim system RAM...\n")
                log_file.flush()
                subprocess.run(stop_cmd, cwd=project_root, env=env, capture_output=True, timeout=15)
                log_file.write("[SYSTEM] Background Gradle Daemons stopped successfully.\n")
                log_file.flush()
            except Exception as se:
                log_file.write(f"[WARNING] Could not stop background daemons: {se}\n")
                log_file.flush()

            # 4. Run Gradle Build subprocess inside a retry-loop for self-healing missing SDK/tools
            max_attempts = 2
            build_succeeded = False
            
            for attempt in range(1, max_attempts + 1):
                log_file.write(f"[SYSTEM] Executing: {' '.join(cmd)} (Build Attempt {attempt}/{max_attempts})\n\n")
                log_file.flush()
                
                process = None
                try:
                    process = subprocess.Popen(
                        cmd,
                        cwd=project_root,
                        stdout=log_file,
                        stderr=log_file,
                        env=env,
                        text=True
                    )
                    active_processes[build_id] = process
                    
                    exit_code = process.wait()
                    
                    # Handle intentional cancellation
                    if build_id in canceled_builds:
                        log_file.write("\nBUILD FAILED\n")
                        log_file.write("Reason: Build was cancelled by the user.\n")
                        log_file.flush()
                        raise RuntimeError("Build was cancelled by the user.")
                    
                    if exit_code == 0:
                        log_file.write("\nBUILD SUCCESSFUL\n")
                        log_file.write("Gradle build completed successfully.\n")
                        log_file.flush()
                        build_succeeded = True
                        break
                        
                    # Build failed, check logs for self-healing
                    log_file.write(f"\nBUILD FAILED (exit code {exit_code}). Running diagnostic check...\n")
                    log_file.flush()
                    
                    # Read the log file to parse missing SDK items
                    try:
                        with open(log_file_path, "r", encoding="utf-8", errors="replace") as lf:
                            log_content = lf.read()
                    except Exception as le:
                        log_content = ""
                        logger.error(f"Could not read log file for self-healing: {le}")
                        
                    # Try to install missing SDK components
                    if attempt < max_attempts and heal_missing_sdk_components(log_content, log_file, sdk_path):
                        log_file.write("\n[SYSTEM] Missing SDK components installed successfully. Restarting compilation...\n\n")
                        log_file.flush()
                        continue
                    else:
                        log_file.write("\n[ERROR] Build pipeline interrupted / Gradle Daemon reuse failure.\n")
                        log_file.write("Reason: Stale, orphaned Gradle Daemons or processes are occupying the server's memory (RAM).\n")
                        log_file.write("This frequently occurs when the build sandbox runs out of memory or a process crashes.\n\n")
                        log_file.write("Action Steps to Resolve:\n")
                        log_file.write("1. Click the 'Clear Session' button in the top navigation bar to reset local cache folders.\n")
                        log_file.write("2. Wait a few seconds to let system processes clear out, then click 'Build APK' to try compilation again.\n")
                        log_file.write("3. If this continues, restart the server or run 'gradle --stop' locally to terminate stale processes.\n\n")
                        log_file.flush()
                        raise RuntimeError(f"Gradle build failed with exit code {exit_code}. Memory exhaustion or stale daemon lock occurred.")
                        
                except FileNotFoundError as fnfe:
                    log_file.write(f"\n[ERROR] Gradle executable not found.\n")
                    log_file.write("The project is missing the Gradle Wrapper (gradlew.bat/gradlew) files,\n")
                    log_file.write("and the global 'gradle' fallback command is not installed or not in your system PATH.\n\n")
                    log_file.write("To resolve this:\n")
                    log_file.write("1. Copy 'gradlew', 'gradlew.bat', and the 'gradle' directory from a working Android project into your project root.\n")
                    log_file.write("2. Or install Gradle globally on your computer (https://gradle.org/install/) and add its 'bin' folder to your system PATH.\n")
                    log_file.write("\nBUILD FAILED\n")
                    raise RuntimeError("Gradle executable not found on the system path.") from fnfe
                except Exception as e:
                    if process and process.poll() is None:
                        process.terminate()
                    log_file.write(f"\nBUILD FAILED\n")
                    log_file.write(f"Reason: {str(e)}\n")
                    raise e
                    
            if not build_succeeded:
                raise RuntimeError("Build compilation failed after self-healing attempts.")
                
            # 5. Locate APK and move it to apks/
            apks = find_apks(project_root)
            if not apks:
                log_file.write("[ERROR] Build succeeded but no APK output file was found.\n")
                log_file.write("BUILD FAILED\n")
                raise RuntimeError("Build completed successfully, but no APK output was found.")
                
            apk_src = apks[0]
            log_file.write(f"[SYSTEM] Located generated APK: {apk_src}\n")
            
            # Prepare target path
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            apks_dir = os.path.join(base_dir, 'apks')
            os.makedirs(apks_dir, exist_ok=True)
            
            # Sanitize output filename
            apk_id = str(uuid.uuid4())
            clean_name = os.path.splitext(os.path.basename(original_filename))[0]
            clean_name = "".join(c for c in clean_name if c.isalnum() or c in ('-', '_')).strip()
            if not clean_name:
                clean_name = "app"
            apk_dest_filename = f"{clean_name}-{apk_id[:8]}.apk"
            apk_dest = os.path.join(apks_dir, apk_dest_filename)
            
            # Copy to target
            shutil.copy2(apk_src, apk_dest)
            
            size_bytes = os.path.getsize(apk_dest)
            duration = round(time.time() - start_time, 2)
            
            # Save metadata and print required logs
            add_apk_metadata(apk_id, apk_dest_filename, original_filename, size_bytes, duration)
            
            log_file.write(f"[SYSTEM] APK generated successfully.\n")
            log_file.write(f"[SYSTEM] File: {apk_dest_filename} ({round(size_bytes / (1024*1024), 2)} MB)\n")
            log_file.write(f"[SYSTEM] Build Duration: {duration} seconds\n")
            log_file.flush()
            
            return {
                "apk_id": apk_id,
                "filename": apk_dest_filename,
                "size_bytes": size_bytes,
                "duration_seconds": duration
            }
            
    finally:
        active_processes.pop(build_id, None)
        canceled_builds.discard(build_id)
        # Cleanup temporary files (Delete temporary project directory)
        # Keep only the generated APK
        if temp_dir and os.path.exists(temp_dir):
            try:
                cleanup_directory(temp_dir)
                logger.info(f"Cleaned up temporary project directory: {temp_dir}")
            except Exception as e:
                logger.error(f"Failed to clean up temp dir {temp_dir}: {e}")
