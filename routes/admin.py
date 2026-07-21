# admin.py - COMBINED MASTER ADMIN & CLIENT AUDIT LEDGER ROUTER
from flask import Blueprint, render_template, request, redirect, session
from modules.database import InventoryDB
import pandas as pd
import sqlite3
import os

admin_bp = Blueprint('admin', __name__)
USER_DB_PATH = "data/users.db"

# Master Admin Credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "KnifeAndEmberAdmin2026!"


# =========================================================
# 🔑 1. MASTER SYSTEM ADMIN ROUTES (GLOBAL CONTROL)
# =========================================================

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


# =========================================================
# 📜 2. CLIENT STORE AUDIT LOGS ROUTE (PER STORE LEDGER)
# =========================================================

@admin_bp.route('/portal/<username>/audit-logs', methods=['GET'])
def web_audit_logs_tab(username):
    username = username.lower().strip()
    
    # Allow access if logged in as the store owner OR as master admin
    if session.get('logged_in_user') != username and not session.get('is_admin'): 
        return redirect('/login')
    
    db = InventoryDB(f"data/client_{username}.db")
    
    # Get URL filtering parameters
    selected_module = request.args.get('module', 'All')
    selected_user = request.args.get('user', 'All')
    
    # Fetch logs from database.py
    df_logs = db.get_audit_logs(limit=300, module=selected_module, username=selected_user)
    
    logs_list = []
    modules_list = []
    users_list = []
    total_count = 0
    
    # Read master log lists to populate filter dropdown options
    df_all_logs = db.read_tab('Audit_Logs')
    if not df_all_logs.empty:
        if 'Module' in df_all_logs.columns:
            modules_list = sorted([m for m in df_all_logs['Module'].dropna().unique() if m])
        if 'Username' in df_all_logs.columns:
            users_list = sorted([u for u in df_all_logs['Username'].dropna().unique() if u])
            
    if not df_logs.empty:
        # Format timestamps nicely for display
        if 'Timestamp' in df_logs.columns:
            df_logs['Timestamp_Str'] = pd.to_datetime(df_logs['Timestamp'], errors='coerce').dt.strftime('%Y-%m-%d %I:%M:%S %p')
        else:
            df_logs['Timestamp_Str'] = ''
            
        total_count = len(df_logs)
        logs_list = df_logs.to_dict('records')
        
    return render_template(
        'audit_logs.html',
        username=username,
        logs=logs_list,
        modules=modules_list,
        users=users_list,
        current_module=selected_module,
        current_user=selected_user,
        total_count=total_count
    )