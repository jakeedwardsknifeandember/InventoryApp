from flask import Blueprint, render_template, request, redirect, session
import sqlite3
import os

admin_bp = Blueprint('admin', __name__)
USER_DB_PATH = "data/users.db"

# Master Admin Credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "KnifeAndEmberAdmin2026!"

@admin_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect('/admin/dashboard')
        else:
            error = "Invalid master admin credentials."
            
    return render_template('admin_login.html', error=error)

@admin_bp.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect('/admin/login')

    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(USER_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, database_file, subscription_status FROM users")
    records = cursor.fetchall()
    conn.close()

    users = []
    for row in records:
        users.append({
            'username': row[0],
            'password': row[1],
            'database': row[2],
            'status': row[3]
        })

    return render_template('admin_dashboard.html', users=users)

@admin_bp.route('/admin/create_client', methods=['POST'])
def create_client():
    if not session.get('is_admin'):
        return redirect('/admin/login')

    username = request.form.get('username', '').lower().strip()
    password = request.form.get('password', '').strip()
    status = request.form.get('status', 'Active')

    if username and password:
        client_db_path = f"data/client_{username}.db"
        
        conn = sqlite3.connect(USER_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)",
            (username, password, client_db_path, status)
        )
        conn.commit()
        conn.close()

    return redirect('/admin/dashboard')

@admin_bp.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect('/admin/login')