import os
import logging
from flask import Flask
from routes.main import main_bp
from routes.stream import stream_bp
from services.cleaner import start_cleanup_scheduler

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    
    # Configure maximum file upload size (150 MB)
    app.config['MAX_CONTENT_LENGTH'] = 150 * 1024 * 1024
    
    # Initialize necessary folders
    base_dir = os.path.dirname(os.path.abspath(__file__))
    folders = ['uploads', 'temp', 'apks', 'logs']
    for folder in folders:
        folder_path = os.path.join(base_dir, folder)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path, exist_ok=True)
            logger.info(f"Created directory: {folder_path}")
            
    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(stream_bp)
    
    # Start the background scheduler for APK deletion (scans every 60 seconds)
    start_cleanup_scheduler(interval_seconds=60)
    
    return app

app = create_app()

if __name__ == '__main__':
    # Determine port from env or fallback to 5000
    port = int(os.environ.get('PORT', 5000))
    # Enable debug mode only if explicitly enabled via environment variable
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 't']
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

