import os
import time
import logging
from flask import Blueprint, Response

logger = logging.getLogger(__name__)

stream_bp = Blueprint('stream', __name__)

def get_logs_dir():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'logs')

@stream_bp.route('/stream/<build_id>')
def stream_logs(build_id):
    log_path = os.path.join(get_logs_dir(), f"{build_id}.log")
    status_path = os.path.join(get_logs_dir(), f"{build_id}.status")
    
    def generate():
        # Wait up to 5 seconds for the log file to be initialized by the thread
        retries = 10
        while not os.path.exists(log_path) and retries > 0:
            time.sleep(0.5)
            retries -= 1
            
        if not os.path.exists(log_path):
            yield "data: [SYSTEM] ERROR: Log file initialization timed out.\n\n"
            yield "data: BUILD FAILED\n\n"
            yield "data: [SYSTEM] EOF\n\n"
            return
            
        # Read file from start
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            # Yield existing contents first
            while True:
                line = f.readline()
                if not line:
                    break
                yield f"data: {line.rstrip()}\n\n"
            
            # Keep reading new lines while build is running
            while True:
                line = f.readline()
                if line:
                    yield f"data: {line.rstrip()}\n\n"
                else:
                    # Check status to see if compilation finished
                    status = "RUNNING"
                    if os.path.exists(status_path):
                        try:
                            with open(status_path, 'r', encoding='utf-8') as sf:
                                status = sf.read().strip()
                        except Exception as e:
                            logger.error(f"Error checking status for streaming: {e}")
                    
                    if status == "RUNNING":
                        pass
                    
                    if not status.startswith("RUNNING") and status != "UNKNOWN":
                        # Flush any remaining logs that were written just as status was changing
                        time.sleep(0.2)
                        while True:
                            line = f.readline()
                            if not line:
                                break
                            yield f"data: {line.rstrip()}\n\n"
                        break
                        
                    # Yield empty heartbeat or just sleep
                    yield ":\n\n"
                    time.sleep(0.5)
                    
        # Signal connection close
        yield "data: [SYSTEM] EOF\n\n"
        
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',  # Disables buffering in Nginx
        'Connection': 'keep-alive'
    })
