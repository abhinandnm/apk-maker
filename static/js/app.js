let buildTimer = null;
let startTime = 0;
let eventSource = null;
let progressVal = 0;
let currentBuildId = null;

// Switch between Git URL and ZIP file upload
function switchTab(type) {
    document.getElementById('input-type').value = type;
    
    // Toggle active tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`tab-${type}`).classList.add('active');
    
    // Toggle active form section
    document.querySelectorAll('.form-section').forEach(sec => sec.classList.remove('active'));
    document.getElementById(`${type}-section`).classList.add('active');
    
    // Manage input requirements
    if (type === 'git') {
        document.getElementById('git_url').setAttribute('required', 'required');
    } else {
        document.getElementById('git_url').removeAttribute('required');
    }
}

// Handle local file selection
function handleFileSelected(input) {
    const fileInfo = document.getElementById('file-info');
    const label = document.getElementById('upload-label');
    
    if (input.files.length > 0) {
        const file = input.files[0];
        const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
        
        label.innerText = "Selected File:";
        fileInfo.innerText = `${file.name} (${sizeMb} MB)`;
        fileInfo.style.display = 'inline-block';
    } else {
        label.innerText = "Drag & drop your ZIP file, or click to browse";
        fileInfo.style.display = 'none';
    }
}

// Support Drag & Drop events
const dropzone = document.querySelector('.upload-dropzone');
if (dropzone) {
    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.style.borderColor = 'var(--color-cyan)';
            dropzone.style.background = 'rgba(0, 229, 255, 0.03)';
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.style.borderColor = 'var(--border-color)';
            dropzone.style.background = 'rgba(2, 4, 8, 0.2)';
        }, false);
    });

    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        const fileInput = document.getElementById('zip_file');
        
        if (files.length > 0 && files[0].name.toLowerCase().endsWith('.zip')) {
            fileInput.files = files;
            handleFileSelected(fileInput);
        } else {
            alert("Only ZIP files are supported!");
        }
    });
}

// Clear simulated terminal output
function clearTerminal() {
    const terminal = document.getElementById('terminal');
    terminal.innerHTML = '<div class="terminal-line system">Terminal log cleared. Ready.</div>';
}

// Append formatted line to terminal
function appendLog(text, type = '') {
    const terminal = document.getElementById('terminal');
    const line = document.createElement('div');
    line.className = `terminal-line ${type}`;
    line.textContent = text;
    terminal.appendChild(line);
    
    // Auto scroll to bottom
    terminal.scrollTop = terminal.scrollHeight;
}

// Parse build log lines for tasks and progress updates
function parseLogForProgress(line) {
    const progressText = document.getElementById('status-percentage');
    const progressBar = document.getElementById('progress-bar');
    const taskText = document.getElementById('current-task');
    
    // Detect key events in logs
    if (line.includes('[SYSTEM] Cloning repository')) {
        progressVal = 5;
        progressBar.style.width = '5%';
        progressText.innerText = '5%';
        taskText.innerText = 'Cloning Git Repository';
    } 
    else if (line.includes('[SYSTEM] Extracting uploaded project ZIP')) {
        progressVal = 10;
        progressBar.style.width = '10%';
        progressText.innerText = '10%';
        taskText.innerText = 'Extracting uploaded ZIP archive';
    }
    else if (line.includes('[SYSTEM] Created local.properties')) {
        progressVal = 18;
        progressBar.style.width = '18%';
        progressText.innerText = '18%';
        taskText.innerText = 'Configuring Android environment';
    }
    else if (line.includes('Executing command:')) {
        progressVal = 25;
        progressBar.style.width = '25%';
        progressText.innerText = '25%';
        taskText.innerText = 'Initializing Gradle Compilation';
    }
    else if (line.includes('> Task :')) {
        // Extract Task Name (e.g. > Task :app:compileDebugJavaWithJavac)
        const match = line.match(/> Task (:[\w:]+)/);
        if (match) {
            taskText.innerText = `Executing Gradle Task: ${match[1]}`;
            // Incrementally move progress up to 90% based on completed compilation tasks
            if (progressVal < 90) {
                progressVal += 1.5;
                if (progressVal > 90) progressVal = 90;
                const displayVal = Math.round(progressVal);
                progressBar.style.width = `${displayVal}%`;
                progressText.innerText = `${displayVal}%`;
            }
        }
    }
    else if (line.includes('BUILD SUCCESSFUL')) {
        progressBar.style.width = '100%';
        progressText.innerText = '100%';
        taskText.innerText = 'Build finished successfully';
        document.getElementById('status-title').innerText = 'Status: SUCCESSFUL';
        progressBar.style.background = 'linear-gradient(90deg, var(--color-green), #00c853)';
    }
    else if (line.includes('BUILD FAILED') || line.includes('[ERROR]')) {
        taskText.innerText = 'Build pipeline failed';
        document.getElementById('status-title').innerText = 'Status: FAILED';
        progressBar.style.background = 'var(--color-red)';
    }
}

// Timer management
function startTimer(customStartTime) {
    startTime = customStartTime || Date.now();
    const timerVal = document.getElementById('timer');
    
    if (buildTimer) {
        clearInterval(buildTimer);
    }
    
    buildTimer = setInterval(() => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        timerVal.innerText = `${elapsed}s`;
    }, 100);
}

function stopTimer() {
    if (buildTimer) {
        clearInterval(buildTimer);
        buildTimer = null;
    }
}

// Check build status via REST endpoint
function checkBuildStatus(buildId) {
    fetch(`/build-status/${buildId}`)
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                stopTimer();
                
                // Update build status cards
                document.getElementById('tracker-panel').style.display = 'none';
                
                document.getElementById('meta-original-name').innerText = data.original_name || data.filename;
                document.getElementById('meta-filename').innerText = data.filename;
                
                // Format size
                const sizeMb = (data.size_bytes / (1024 * 1024)).toFixed(2);
                document.getElementById('meta-size').innerText = `${sizeMb} MB`;
                document.getElementById('meta-duration').innerText = `${data.duration_seconds} seconds`;
                
                // Bind Download APK link
                const downloadBtn = document.getElementById('download-btn');
                downloadBtn.setAttribute('href', `/download/${data.apk_id}`);
                
                document.getElementById('success-box').style.display = 'block';
                appendLog("[SYSTEM] APK available for download.", "success");
                loadRecentBuilds();
            } 
            else if (data.status === 'failed') {
                stopTimer();
                appendLog(`[SYSTEM] Compilation aborted. Reason: ${data.error}`, "error");
                enableSubmitButton(true);
            }
            else if (data.status === 'running') {
                // If it is somehow still running but SSE closed, reconnect or keep polling
                setTimeout(() => checkBuildStatus(buildId), 2000);
            }
        })
        .catch(err => {
            console.error("Failed to fetch build status:", err);
            appendLog(`[SYSTEM] Warning: Could not retrieve final build status. Retrying...`, "warning");
            setTimeout(() => checkBuildStatus(buildId), 3000);
        });
}

function enableSubmitButton(enabled) {
    const btn = document.getElementById('submit-btn');
    const spinner = btn.querySelector('.spinner');
    const btnText = btn.querySelector('span');
    const cancelBtn = document.getElementById('cancel-build-btn');
    
    if (enabled) {
        btn.removeAttribute('disabled');
        spinner.style.display = 'none';
        btnText.innerText = "Build APK";
        if (cancelBtn) cancelBtn.style.display = 'none';
    } else {
        btn.setAttribute('disabled', 'disabled');
        spinner.style.display = 'block';
        btnText.innerText = "Compiling...";
        if (cancelBtn && currentBuildId) cancelBtn.style.display = 'inline-flex';
    }
}

// Helper to connect log stream, parse progress and manage timer
function connectLogStream(buildId, createdAt) {
    if (eventSource) {
        eventSource.close();
    }
    
    currentBuildId = buildId;
    window._buildSuccessHandled = false;
    
    // UI resets
    clearTerminal();
    document.getElementById('success-box').style.display = 'none';
    document.getElementById('tracker-panel').style.display = 'block';
    document.getElementById('status-title').innerText = 'Status: Compiling...';
    document.getElementById('status-percentage').innerText = '0%';
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, var(--color-cyan), var(--color-blue))';
    document.getElementById('current-task').innerText = 'Contacting server...';
    
    enableSubmitButton(false);
    
    // Set up Cancel button in tracker panel
    const cancelBtn = document.getElementById('cancel-build-btn');
    if (cancelBtn) {
        cancelBtn.style.display = 'inline-flex';
        cancelBtn.onclick = () => cancelBuild(buildId);
    }
    
    // Start or resume timer
    const startMs = createdAt ? new Date(createdAt).getTime() : Date.now();
    startTimer(startMs);
    
    eventSource = new EventSource(`/stream/${buildId}`);
    
    eventSource.onmessage = function(e) {
        const line = e.data;
        
        // Check for end of stream
        if (line === "[SYSTEM] EOF") {
            eventSource.close();
            appendLog("[SYSTEM] Log stream connection closed.", "system");
            if (!window._buildSuccessHandled) {
                checkBuildStatus(buildId);
                enableSubmitButton(true);
            }
            return;
        }
        
        // Log classifications for terminal colors
        let type = '';
        if (line.includes('BUILD FAILED') || line.includes('[ERROR]') || line.includes('Reason:')) {
            type = 'error';
        } 
        else if (line.includes('BUILD SUCCESSFUL') || line.includes('[SYSTEM] APK generated successfully')) {
            type = 'success';
        }
        else if (line.includes('[SYSTEM]')) {
            type = 'system';
        }
        else if (line.includes('[WARNING]')) {
            type = 'warning';
        }
        
        appendLog(line, type);
        parseLogForProgress(line);

        // ── Instant success: stop timer + show download button immediately ──
        if (line.includes('[SYSTEM] APK generated successfully') || line.includes('[SYSTEM] File:')) {
            stopTimer();
            window._buildSuccessHandled = true;
            enableSubmitButton(true);
            setTimeout(() => checkBuildStatus(buildId), 800);
        }

        // Stop timer immediately on failure too
        if (line.includes('BUILD FAILED') && !line.includes('Running diagnostic')) {
            stopTimer();
            enableSubmitButton(true);
        }
    };
    
    eventSource.onerror = function(err) {
        console.error("EventSource encountered an error:", err);
        appendLog("[SYSTEM] Connection interrupted. Reconnecting log stream...", "warning");
    };
}

// Main Submit Form Logic
function submitBuild(event) {
    event.preventDefault();
    
    enableSubmitButton(false);
    clearTerminal();
    appendLog("[SYSTEM] Initializing build request...", "system");
    
    const form = document.getElementById('build-form');
    const formData = new FormData(form);
    
    fetch('/build', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => { throw new Error(err.error || 'Server error occurred') });
        }
        return response.json();
    })
    .then(data => {
        const buildId = data.build_id;
        appendLog(`[SYSTEM] Server accepted request. Build ID generated: ${buildId}`, "system");
        connectLogStream(buildId, null);
    })
    .catch(error => {
        stopTimer();
        enableSubmitButton(true);
        document.getElementById('tracker-panel').style.display = 'none';
        appendLog(`[ERROR] Build dispatch failed: ${error.message}`, "error");
    });
}

function trackBuild(buildId, createdAt) {
    appendLog(`[SYSTEM] Reconnecting to running build: ${buildId}`, "system");
    connectLogStream(buildId, createdAt);
}

// Load recent builds on page initialization and after updates
function loadRecentBuilds() {
    const listContainer = document.getElementById('recent-builds-list');
    if (!listContainer) return;
    
    fetch('/recent-builds')
        .then(response => response.json())
        .then(builds => {
            listContainer.innerHTML = '';
            
            if (builds.length === 0) {
                listContainer.innerHTML = '<div class="no-builds-msg">No active builds. Compiled APKs will appear here.</div>';
                return;
            }
            
            builds.forEach(build => {
                const card = document.createElement('div');
                card.className = 'recent-build-card';
                
                if (build.status === 'running') {
                    card.style.cursor = 'pointer';
                    card.title = 'Click to view build progress and logs';
                    card.onclick = (e) => {
                        if (e.target.closest('button') || e.target.closest('a')) return;
                        trackBuild(build.build_id, build.created_at);
                    };
                }
                
                let sizeDisplay = '';
                if (build.size_bytes) {
                    sizeDisplay = (build.size_bytes / (1024 * 1024)).toFixed(2) + ' MB';
                } else {
                    sizeDisplay = 'N/A';
                }
                
                let actionHTML = '';
                if (build.status === 'success') {
                    actionHTML = `<a href="/download/${build.apk_id}" class="recent-download-btn" download>Download</a>`;
                } else if (build.status === 'running') {
                    actionHTML = `<div style="display:flex; align-items:center; gap: 10px;">
                                    <div style="display:flex; align-items:center; color: var(--color-blue); font-size: 13px;">
                                        <div class="spinner" style="display:inline-block; width:12px; height:12px; border-width: 2px; border-top-color: var(--color-blue); margin-right: 6px;"></div>
                                        Building...
                                    </div>
                                    <button type="button" onclick="cancelBuild('${build.build_id}')" style="background:transparent; border:1px solid var(--color-red); color:var(--color-red); border-radius:4px; padding:3px 8px; font-size:11px; cursor:pointer;">Cancel</button>
                                  </div>`;
                } else {
                    actionHTML = `<span style="color: var(--color-red); font-size: 13px; font-weight: 500;">Failed</span>`;
                }
                
                card.innerHTML = `
                    <div class="build-info">
                        <div class="build-name" title="${build.original_name}">${build.original_name}</div>
                        <div class="build-meta-row">
                            <span>${sizeDisplay}</span>
                            <span>•</span>
                            <span class="build-time-rem" ${build.status === 'failed' ? 'style="color:var(--color-red);"' : ''}>${build.time_remaining}</span>
                        </div>
                    </div>
                    ${actionHTML}
                `;
                listContainer.appendChild(card);
            });
        })
        .catch(err => {
            console.error("Failed to load recent builds:", err);
            listContainer.innerHTML = '<div class="no-builds-msg" style="color: var(--color-red);">Failed to load history</div>';
        });
}

// Clear all local data in server (Settings Option)
function confirmClearAllData() {
    const confirmation = confirm("Are you sure you want to clear all local data on the server? This will permanently delete all compiled APKs, build logs, uploads, and temporary folders.");
    if (!confirmation) return;
    
    fetch('/clear-all-data', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            alert(data.message);
            // Hide trackers & success boxes
            document.getElementById('tracker-panel').style.display = 'none';
            document.getElementById('success-box').style.display = 'none';
            clearTerminal();
            // Refresh recent builds list
            loadRecentBuilds();
        })
        .catch(err => {
            console.error("Error clearing server data:", err);
            alert("Failed to clear data: " + err.message);
        });
}

// Run initial configurations
document.addEventListener("DOMContentLoaded", () => {
    loadRecentBuilds();
});

// Cancel an ongoing build
function cancelBuild(buildId) {
    if (!confirm('Are you sure you want to cancel this build?')) return;
    
    fetch(`/cancel-build/${buildId}`, { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                appendLog('[SYSTEM] Build was cancelled by user.', 'warning');
            } else {
                appendLog(`[SYSTEM] Failed to cancel: ${data.message}`, 'error');
            }
            // Refresh the builds list immediately
            loadRecentBuilds();
        })
        .catch(err => {
            console.error('Cancel failed:', err);
        });
}

// Notifications Logic
function toggleNotifications() {
    const dropdown = document.getElementById('notification-dropdown');
    const content = document.getElementById('notification-content');
    
    if (dropdown.style.display === 'none') {
        dropdown.style.display = 'block';
        content.innerHTML = '<div class="spinner" style="display:block; margin: 0 auto; width:16px; height:16px; border-width: 2px; border-top-color: var(--color-blue);"></div>';
        
        fetch('/latest-update')
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    content.innerHTML = `
                        <div style="margin-bottom: 8px;">
                            <span style="font-family: monospace; background: #eaeded; padding: 2px 4px; border-radius: 3px; font-weight: bold; color: #545b64;">${data.hash}</span>
                            <span style="color: #545b64; margin-left: 5px;">${data.time}</span>
                        </div>
                        <div style="color: #16191f; line-height: 1.4;">${data.message}</div>
                    `;
                } else {
                    content.innerHTML = `<div style="color: var(--color-red);">${data.message}</div>`;
                }
            })
            .catch(err => {
                content.innerHTML = `<div style="color: var(--color-red);">Failed to load updates.</div>`;
            });
    } else {
        dropdown.style.display = 'none';
    }
}

// Close dropdown if clicked outside
document.addEventListener('click', function(event) {
    const dropdown = document.getElementById('notification-dropdown');
    const btn = document.getElementById('notification-btn');
    if (dropdown && btn && dropdown.style.display === 'block') {
        if (!dropdown.contains(event.target) && !btn.contains(event.target)) {
            dropdown.style.display = 'none';
        }
    }
});
