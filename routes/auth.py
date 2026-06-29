# routes/auth.py - Authentication Module (Login/Logout Routing)
from flask import Blueprint, request, redirect, url_for, session, render_template
import sqlite3

# 🌟 This acts as our mini-app engine specifically for authentication
auth_bp = Blueprint('auth', __name__)

USER_DB_PATH = "data/users.db"

@auth_bp.route('/')
def index():
    if 'logged_in_user' in session: 
        # FIXED: Enforced matching direct literal path routing to eliminate the url_for BuildError
        return redirect(f"/portal/{session['logged_in_user']}")
    return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        input_user = request.form['username'].lower().strip()
        input_pass = request.form['password']
        
        conn = sqlite3.connect(USER_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT password, subscription_status FROM users WHERE username = ?", (input_user,))
        user_record = cursor.fetchone()
        conn.close()
        
        if user_record and input_pass == user_record[0] and user_record[1] == 'Active':
            session['logged_in_user'] = input_user
            # Redirect to the main client portal dashboard
            return redirect(f"/portal/{input_user}")
        error = "❌ Invalid credentials."
        
    return render_template('login.html', error=error)

@auth_bp.route('/logout')
def logout():
    session.pop('logged_in_user', None)
    return redirect(url_for('auth.login'))