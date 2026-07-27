import os
import uuid
import json
import urllib.request
import urllib.parse
import logging
from flask import Blueprint, request, redirect, session, jsonify, url_for, render_template

from services.db import upsert_user

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# Load GitHub Client Credentials from Environment
GITHUB_CLIENT_ID = os.environ.get('GITHUB_CLIENT_ID', '').strip()
GITHUB_CLIENT_SECRET = os.environ.get('GITHUB_CLIENT_SECRET', '').strip()

@auth_bp.route('/auth/login')
def login():
    """Redirects user to GitHub OAuth login page, or shows error if not configured."""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        # If credentials are not configured, redirect back with query parameter
        logger.warning("GitHub OAuth client credentials are not configured. Redirecting to home with warning.")
        return redirect(url_for('main.index', error='github_not_configured'))
        
    state = str(uuid.uuid4())
    session['oauth_state'] = state
    
    params = {
        'client_id': GITHUB_CLIENT_ID,
        'scope': 'read:user',
        'state': state
    }
    auth_url = f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)

@auth_bp.route('/auth/callback')
def callback():
    """Handles GitHub redirect callback and exchanges code for access token."""
    code = request.args.get('code')
    state = request.args.get('state')
    
    # Verify state to protect against CSRF
    stored_state = session.pop('oauth_state', None)
    if not state or state != stored_state:
        logger.error("State validation failed during GitHub OAuth callback.")
        return render_template('error.html', message="Session expired or invalid state. Please try logging in again."), 400
        
    if not code:
        logger.error("Missing authorization code in GitHub callback.")
        return redirect(url_for('main.index'))
        
    try:
        # 1. Exchange authorization code for access token
        token_data = urllib.parse.urlencode({
            'client_id': GITHUB_CLIENT_ID,
            'client_secret': GITHUB_CLIENT_SECRET,
            'code': code,
            'state': state
        }).encode('utf-8')
        
        token_req = urllib.request.Request(
            'https://github.com/login/oauth/access_token',
            data=token_data,
            headers={
                'Accept': 'application/json',
                'User-Agent': 'APK-Builder-Studio'
            }
        )
        
        with urllib.request.urlopen(token_req, timeout=30) as resp:
            token_resp = json.loads(resp.read().decode('utf-8'))
            
        access_token = token_resp.get('access_token')
        if not access_token:
            err_desc = token_resp.get('error_description', 'Unknown error')
            logger.error(f"Failed to retrieve access token: {err_desc}")
            return render_template('error.html', message=f"Failed to authenticate with GitHub: {err_desc}"), 400
            
        # 2. Fetch authenticated user profile details from GitHub API
        user_req = urllib.request.Request(
            'https://api.github.com/user',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json',
                'User-Agent': 'APK-Builder-Studio'
            }
        )
        
        with urllib.request.urlopen(user_req, timeout=30) as resp:
            user_data = json.loads(resp.read().decode('utf-8'))
            
        github_id = str(user_data.get('id'))
        username = user_data.get('login', 'GitHub User')
        avatar_url = user_data.get('avatar_url')
        
        # 3. Upsert user in database and save user info in session
        user_id = upsert_user(github_id, username, avatar_url)
        session['user_id'] = user_id
        session['username'] = username
        session['avatar_url'] = avatar_url
        
        logger.info(f"User {username} successfully logged in via GitHub.")
        return redirect(url_for('main.index'))
        
    except Exception as e:
        logger.error(f"Error during GitHub OAuth callback: {e}")
        return render_template('error.html', message=f"An unexpected error occurred during login: {str(e)}"), 500

@auth_bp.route('/auth/dev-login', methods=['POST'])
def dev_login():
    """Bypasses GitHub authentication and logs in a mockup developer user for local testing."""
    try:
        dev_github_id = "00000000"
        dev_username = "dev_user"
        dev_avatar_url = "https://avatars.githubusercontent.com/u/583231?v=4" # GitHub Octocat avatar
        
        # Save or update user in SQLite
        user_id = upsert_user(dev_github_id, dev_username, dev_avatar_url)
        session['user_id'] = user_id
        session['username'] = dev_username
        session['avatar_url'] = dev_avatar_url
        
        logger.info("Developer bypass mockup login initiated.")
        return jsonify({
            "status": "success",
            "message": "Mock login successful.",
            "user": {
                "username": dev_username,
                "avatar_url": dev_avatar_url
            }
        })
    except Exception as e:
        logger.error(f"Developer bypass login failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@auth_bp.route('/auth/logout', methods=['POST', 'GET'])
def logout():
    """Clears authentication session data and redirects back to home page."""
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('avatar_url', None)
    logger.info("User logged out successfully.")
    
    if request.method == 'POST' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"status": "success", "message": "Logged out successfully."})
    return redirect(url_for('main.index'))

@auth_bp.route('/auth/me')
def me():
    """Returns the profile info for the currently authenticated session, if any."""
    if 'user_id' in session:
        return jsonify({
            "logged_in": True,
            "username": session.get('username'),
            "avatar_url": session.get('avatar_url'),
            "github_configured": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)
        })
    return jsonify({
        "logged_in": False,
        "github_configured": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)
    })
