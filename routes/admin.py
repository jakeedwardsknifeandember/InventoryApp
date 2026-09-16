# routes/admin.py - Master SaaS Platform Controller, Client Provisioning & Multi-Tenant Orchestrator
from flask import Blueprint, render_template, request, redirect, session, flash, send_file
from modules.database import InventoryDB
import pandas as pd
import sqlite3
import os
import io

admin_bp = Blueprint('admin', __name__)
USER_DB_PATH = "data/users.db"

# Master Platform Admin Credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "KnifeAndEmberAdmin2026!"

def get_users_db_connection():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(USER_DB_PATH, timeout=20.0)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            database_file TEXT NOT NULL,
            subscription_status TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def seed_client_database(db_path, username):
    """Provisions and seeds all required operational tables for a newly registered tenant."""
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Products (
            Product_ID TEXT PRIMARY KEY,
            Product_Name TEXT,
            Parent_Item TEXT,
            Variant_Name TEXT,
            Category TEXT,
            Selling_Price REAL DEFAULT 0.0,
            Cost_Price REAL DEFAULT 0.0,
            Margin_Percentage REAL DEFAULT 0.0,
            Active TEXT DEFAULT 'Yes'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Ingredients (
            Ingredient_ID TEXT PRIMARY KEY,
            Ingredient_Name TEXT,
            Unit TEXT,
            Category TEXT,
            Ingredient_Type TEXT DEFAULT 'RAW',
            Current_Stock REAL DEFAULT 0.0,
            Min_Stock REAL DEFAULT 0.0,
            Purchase_Cost REAL DEFAULT 0.0,
            Pack_Size REAL DEFAULT 1.0,
            Cost_Per_Unit REAL DEFAULT 0.0,
            Active TEXT DEFAULT 'Yes'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Recipes (
            Recipe_ID TEXT PRIMARY KEY,
            Product_ID TEXT,
            Ingredient_ID TEXT,
            Quantity_Required REAL DEFAULT 0.0,
            Unit TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Prep_Recipes (
            Prep_Recipe_ID TEXT PRIMARY KEY,
            Prepped_Ingredient_ID TEXT,
            Raw_Ingredient_ID TEXT,
            Quantity_Required REAL DEFAULT 0.0,
            Unit TEXT,
            Batch_Yield REAL DEFAULT 1.0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Modifiers (
            Modifier_ID TEXT PRIMARY KEY,
            Modifier_Name TEXT,
            Category TEXT,
            Price REAL DEFAULT 0.0,
            Active TEXT DEFAULT 'Yes'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Modifier_Recipes (
            Modifier_Recipe_ID TEXT PRIMARY KEY,
            Modifier_ID TEXT,
            Ingredient_ID TEXT,
            Quantity_Required REAL DEFAULT 0.0,
            Unit TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Categories (
            Category_ID TEXT PRIMARY KEY,
            Category_Name TEXT UNIQUE,
            Active TEXT DEFAULT 'Yes'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Sales (
            Sale_ID TEXT PRIMARY KEY,
            Sale_Date TEXT,
            Sale_Time TEXT,
            Product_ID TEXT,
            Product_Name TEXT,
            Quantity REAL,
            Price REAL,
            Total_Amount REAL,
            Reason TEXT,
            Recorded_By TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Expenses (
            Expense_ID TEXT PRIMARY KEY,
            Date TEXT,
            Category TEXT,
            Description TEXT,
            Amount REAL,
            Recorded_By TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Inventory_Audit_Log (
            Audit_ID TEXT,
            Date TEXT,
            Ingredient_Name TEXT,
            Theoretical REAL,
            Physical REAL,
            Variance REAL,
            Notes TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Cash_Drawer_Logs (
            Drawer_Tx_ID TEXT PRIMARY KEY,
            Batch_ID TEXT,
            Date TEXT,
            Time TEXT,
            Starting_Float REAL DEFAULT 0.0,
            Cash_Sales REAL DEFAULT 0.0,
            Cash_Paid_Outs REAL DEFAULT 0.0,
            Expected_Cash REAL DEFAULT 0.0,
            Actual_Counted_Cash REAL DEFAULT 0.0,
            Discrepancy_Over_Short REAL DEFAULT 0.0,
            GCash_Sales REAL DEFAULT 0.0,
            Maya_Sales REAL DEFAULT 0.0,
            Card_Sales REAL DEFAULT 0.0,
            Grab_Gross REAL DEFAULT 0.0,
            Grab_Commission REAL DEFAULT 0.0,
            Grab_Net REAL DEFAULT 0.0,
            Foodpanda_Gross REAL DEFAULT 0.0,
            Foodpanda_Commission REAL DEFAULT 0.0,
            Foodpanda_Net REAL DEFAULT 0.0,
            Total_Settled_Tenders REAL DEFAULT 0.0,
            Tender_Variance REAL DEFAULT 0.0,
            Explanation_Notes TEXT,
            Recorded_By TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Staff_Accounts (
            Staff_ID TEXT PRIMARY KEY,
            Full_Name TEXT,
            Display_Name TEXT,
            Username TEXT UNIQUE,
            Password TEXT,
            PIN TEXT DEFAULT '1234',
            Role TEXT,
            Active TEXT DEFAULT 'Yes'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Store_Settings (
            Setting_Key TEXT PRIMARY KEY,
            Setting_Value TEXT
        )
    """)

    cursor.execute("INSERT OR IGNORE INTO Store_Settings VALUES ('enforce_blind_count', 'yes')")
    cursor.execute("INSERT OR IGNORE INTO Store_Settings VALUES ('variance_alert_pct', '2.0')")
    cursor.execute("INSERT OR IGNORE INTO Store_Settings VALUES ('variance_alert_value', '100.0')")

    starter_cats = ['Espresso Based', 'Non Coffee Based', 'Appetizer', 'Rice Meal', 'Pasta', 'Pizza']
    for idx, c in enumerate(starter_cats, start=1):
        cursor.execute("INSERT OR IGNORE INTO Categories (Category_ID, Category_Name, Active) VALUES (?, ?, 'Yes')", (f"CAT{idx:03d}", c))

    conn.commit()
    conn.close()

# Resolves the 404 error when navigating directly to /admin
@admin_bp.route('/admin', methods=['GET'])
def admin_root():
    if session.get('is_admin'):
        return redirect('/admin/dashboard')
    return redirect('/admin/login')

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
            error = "Invalid master platform credentials."

    return render_template('admin_login.html', error=error)

@admin_bp.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect('/admin/login')

    conn = get_users_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, database_file, subscription_status FROM users ORDER BY username ASC")
    records = cursor.fetchall()
    conn.close()

    total_storage_bytes = 0
    users = []
    for row in records:
        uname = row[0]
        db_file = row[2]
        file_size_kb = 0.0
        product_count = 0
        ingredient_count = 0

        if os.path.exists(db_file):
            size_b = os.path.getsize(db_file)
            total_storage_bytes += size_b
            file_size_kb = round(size_b / 1024.0, 1)

            try:
                c_conn = sqlite3.connect(db_file, timeout=5.0)
                c_cursor = c_conn.cursor()
                c_cursor.execute("SELECT COUNT(*) FROM Products")
                product_count = c_cursor.fetchone()[0]
                c_cursor.execute("SELECT COUNT(*) FROM Ingredients")
                ingredient_count = c_cursor.fetchone()[0]
                c_conn.close()
            except Exception:
                pass

        users.append({
            'username': uname,
            'password': row[1],
            'database': db_file,
            'status': row[3],
            'size_kb': file_size_kb,
            'product_count': product_count,
            'ingredient_count': ingredient_count
        })

    total_storage_mb = round(total_storage_bytes / (1024.0 * 1024.0), 2)
    active_tenants = len([u for u in users if u['status'] == 'Active'])

    return render_template(
        'admin_dashboard.html',
        users=users,
        total_tenants=len(users),
        active_tenants=active_tenants,
        total_storage_mb=total_storage_mb
    )

@admin_bp.route('/admin/create_client', methods=['POST'])
def create_client():
    if not session.get('is_admin'):
        return redirect('/admin/login')

    raw_username = request.form.get('username', '').lower().strip()
    password = request.form.get('password', '').strip()
    status = request.form.get('status', 'Active')

    clean_username = "".join(c for c in raw_username if c.isalnum() or c in ['_', '-'])

    if clean_username and password:
        client_db_path = f"data/client_{clean_username}.db"

        conn = get_users_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO users (username, password, database_file, subscription_status) VALUES (?, ?, ?, ?)",
            (clean_username, password, client_db_path, status)
        )
        conn.commit()
        conn.close()

        seed_client_database(client_db_path, clean_username)
        flash(f"Tenant client '{clean_username}' successfully provisioned.", 'success')

    return redirect('/admin/dashboard')

@admin_bp.route('/admin/impersonate/<username>')
def impersonate_client(username):
    """One-click consultant access: logs master admin directly into the client portal."""
    if not session.get('is_admin'):
        return redirect('/admin/login')

    username = username.lower().strip()
    conn = get_users_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE LOWER(username) = ?", (username,))
    row = cursor.fetchone()
    conn.close()

    if row:
        session['logged_in_user'] = username
        session['staff_role'] = 'Platform Owner Admin'
        session['staff_username'] = f"Admin ({username.title()})"
        return redirect(f"/portal/{username}")
    
    flash("Tenant not found.", "danger")
    return redirect('/admin/dashboard')

@admin_bp.route('/admin/download_db/<username>')
def download_client_db(username):
    """Allows the consultant to download a client's active SQLite database for local auditing."""
    if not session.get('is_admin'):
        return redirect('/admin/login')

    username = username.lower().strip()
    client_db_path = f"data/client_{username}.db"
    if os.path.exists(client_db_path):
        return send_file(client_db_path, as_attachment=True, download_name=f"{username}_audit.db")

    flash("Client database file does not exist.", "danger")
    return redirect('/admin/dashboard')

@admin_bp.route('/admin/update_client', methods=['POST'])
def update_client():
    if not session.get('is_admin'):
        return redirect('/admin/login')

    username = request.form.get('username', '').lower().strip()
    new_password = request.form.get('new_password', '').strip()
    new_status = request.form.get('new_status', '').strip()

    conn = get_users_db_connection()
    cursor = conn.cursor()

    if new_password and new_status:
        cursor.execute("UPDATE users SET password = ?, subscription_status = ? WHERE username = ?", (new_password, new_status, username))
    elif new_password:
        cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_password, username))
    elif new_status:
        cursor.execute("UPDATE users SET subscription_status = ? WHERE username = ?", (new_status, username))

    conn.commit()
    conn.close()
    flash(f"Updated parameters for tenant '{username}'.", "info")
    return redirect('/admin/dashboard')

@admin_bp.route('/admin/delete_client', methods=['POST'])
def delete_client():
    if not session.get('is_admin'):
        return redirect('/admin/login')

    username = request.form.get('username', '').lower().strip()
    if username == 'bakery':
        flash("System Protection: Cannot delete the core default demo account.", 'danger')
        return redirect('/admin/dashboard')

    conn = get_users_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT database_file FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()

    if row and os.path.exists(row[0]):
        try:
            os.remove(row[0])
        except Exception:
            pass

    cursor.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()

    flash(f"Tenant client '{username}' and its database have been purged.", 'warning')
    return redirect('/admin/dashboard')

@admin_bp.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect('/admin/login')

@admin_bp.route('/portal/<username>/audit-logs', methods=['GET'])
def web_audit_logs_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username and not session.get('is_admin'): 
        return redirect('/login')
    
    db = InventoryDB(f"data/client_{username}.db")
    selected_module = request.args.get('module', 'All')
    selected_user = request.args.get('user', 'All')
    
    df_logs = db.get_audit_logs(limit=300, module=selected_module, username=selected_user)
    
    logs_list = []
    modules_list = []
    users_list = []
    total_count = 0
    
    df_all_logs = db.read_tab('Audit_Logs')
    if not df_all_logs.empty:
        if 'Module' in df_all_logs.columns:
            modules_list = sorted([m for m in df_all_logs['Module'].dropna().unique() if m])
        if 'Username' in df_all_logs.columns:
            users_list = sorted([u for u in df_all_logs['Username'].dropna().unique() if u])
            
    if not df_logs.empty:
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