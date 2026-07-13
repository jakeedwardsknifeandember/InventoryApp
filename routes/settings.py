# routes/settings.py - Advanced Enterprise Settings Module with Dynamic Backup & Restore Matrix
from flask import Blueprint, request, redirect, session, render_template, send_file
import sqlite3
import pandas as pd
from datetime import datetime
import os

settings_bp = Blueprint('settings', __name__)

USER_DB_PATH = "data/users.db"

def ensure_staff_table_exists(client_db_path):
    """Provisions the staff roster matrix inside the isolated tenant database if missing"""
    conn = sqlite3.connect(client_db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Staff_Accounts (
            Staff_ID TEXT PRIMARY KEY,
            Username TEXT UNIQUE,
            Password TEXT,
            Role TEXT,
            Active TEXT DEFAULT 'Yes'
        )
    """)
    conn.commit()
    conn.close()

@settings_bp.route('/portal/<username>/settings', methods=['GET', 'POST'])
def web_settings_tab(username):
    username = username.lower().strip()
    
    # 🔒 GATE 1: Verify Core Tenant Session Boundary Isolation
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    # 🩹 BACKWARD COMPATIBILITY AUTOHOTFIX
    # If app.py hasn't been upgraded yet, auto-assign the Admin token to the Master Owner
    if not session.get('staff_role') and session.get('logged_in_user') == username:
        session['staff_role'] = 'Platform Owner Admin'
        
    # 🔒 GATE 2: Enforce Strict Role-Based Security Clearance (Only Master Admins Allowed Here)
    active_role = session.get('staff_role', 'Barista / Kitchen Crew')
    if active_role != 'Platform Owner Admin':
        return redirect(f"/portal/{username}?error=Access Denied: Administrative Settings panel is strictly reserved for the Master Platform Owner Admin.")
        
    client_db_path = f"data/client_{username}.db"
    ensure_staff_table_exists(client_db_path)
    
    feedback_msg = None
    alert_type = "success"

    # ==========================================
    # 📥 1. POST METHOD: PROCESSING CONFIG OPERATIONS
    # ==========================================
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        # ACTION A: CHANGE MAIN PORTAL OWNER PASSWORD
        if action == 'change_password':
            old_p, new_p = request.form.get('old_password'), request.form.get('new_password')
            conn = sqlite3.connect(USER_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
            record = cursor.fetchone()
            
            if record and old_p == record[0]:
                cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_p, username))
                conn.commit()
                feedback_msg = "✅ Success: Master portal login password updated successfully!"
                alert_type = "success"
            else: 
                feedback_msg = "❌ Error: The current password you entered is incorrect."
                alert_type = "danger"
            conn.close()

        # ACTION B: PROVISION NEW ROLES SUB-ACCOUNT
        elif action == 'add_staff':
            staff_user = request.form.get('staff_username', '').lower().strip()
            staff_pass = request.form.get('staff_password', '')
            staff_role = request.form.get('staff_role', 'Barista / Kitchen Crew')
            
            if staff_user and staff_pass:
                conn = sqlite3.connect(client_db_path)
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT COUNT(*) FROM Staff_Accounts")
                    next_id = f"STF{cursor.fetchone()[0] + 1:03d}"
                    
                    cursor.execute(
                        "INSERT INTO Staff_Accounts (Staff_ID, Username, Password, Role, Active) VALUES (?, ?, ?, ?, 'Yes')",
                        (next_id, staff_user, staff_pass, staff_role)
                    )
                    conn.commit()
                    feedback_msg = f"👥 Success: Created sub-account for crew member '{staff_user.capitalize()}' as {staff_role}!"
                    alert_type = "success"
                except sqlite3.IntegrityError:
                    feedback_msg = f"❌ Error: A team sub-account named '{staff_user}' is already registered."
                    alert_type = "danger"
                conn.close()

        # ACTION C: FORCIBLY RESET TEAM USER PASSKEY OVERRIDE
        elif action == 'reset_staff_password':
            staff_id = request.form.get('staff_id')
            new_pass = request.form.get('new_password', '').strip()
            
            if staff_id and new_pass:
                conn = sqlite3.connect(client_db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE Staff_Accounts SET Password = ? WHERE Staff_ID = ?", (new_pass, staff_id))
                conn.commit()
                conn.close()
                feedback_msg = "🔑 Security Override: Staff access token passkey reassigned successfully!"
                alert_type = "success"

        # ACTION D: TERMINATE EMPLOYEE ACCESS
        elif action == 'delete_staff':
            staff_id = request.form.get('staff_id')
            if staff_id:
                conn = sqlite3.connect(client_db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM Staff_Accounts WHERE Staff_ID = ?", (staff_id,))
                conn.commit()
                conn.close()
                feedback_msg = "🗑️ Access terminated: Crew token stripped from active registers cleanly."
                alert_type = "warning"

        # ACTION E: ONE-CLICK LOCAL MACHINE BACKUP COMPRESSION
        elif action == 'backup_database':
            try:
                date_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                return send_file(
                    client_db_path,
                    as_attachment=True,
                    download_name=f"matrix_backup_{username}_{date_stamp}.db"
                )
            except Exception as e:
                feedback_msg = f"❌ Error executing file package packaging: {str(e)}"
                alert_type = "danger"

        # ACTION F: ENTERPRISE DATABASE RESTORE OVERWRITE ENGINE
        elif action == 'restore_database':
            uploaded_file = request.files.get('backup_file')
            if not uploaded_file or uploaded_file.filename == '':
                feedback_msg = "❌ Error: No database backup archive file selected for transmission."
                alert_type = "danger"
            elif not uploaded_file.filename.endswith('.db'):
                feedback_msg = "❌ Error Security Violation: Invalid payload file format. The system only accepts valid operational SQLite `.db` assets."
                alert_type = "danger"
            else:
                try:
                    uploaded_file.save(client_db_path)
                    feedback_msg = "♻️ System Restoration Successful: The database file has been successfully hot-swapped. All historical entries, recipes, and team registries have been cleanly rolled back."
                    alert_type = "success"
                except Exception as e:
                    feedback_msg = f"❌ Restoration Fault during file overwrite sequencing: {str(e)}"
                    alert_type = "danger"

        # 👑 DYNAMIC GRANULAR SELECTIVE DATA RESET CONTROL ENGINE - TRANSACTION FIX APPLIED
        elif action == 'reset_database':
            confirm_input = request.form.get('secure_reset_token', '').strip().upper()
            if confirm_input == 'RESET':
                try:
                    conn = sqlite3.connect(client_db_path)
                    cursor = conn.cursor()
                    
                    tables_to_wipe = []
                    wiped_categories = []
                    
                    if request.form.get('wipe_transactions'):
                        tables_to_wipe.extend(['Sales', 'Inventory_Log', 'Inventory_Audit_Log', 'Expenses'])
                        wiped_categories.append("Operational Activity Logs")
                        
                    if request.form.get('wipe_recipes'):
                        tables_to_wipe.extend(['Recipes', 'Formula_Matrix', 'Recipe_Links', 'Recipe_Items'])
                        wiped_categories.append("Linked Product Recipes")
                        
                    if request.form.get('wipe_ingredients'):
                        tables_to_wipe.extend(['Ingredients', 'Ingredient_Stock', 'Ingredients_Master'])
                        wiped_categories.append("Raw Material Ingredients List")
                        
                    if request.form.get('wipe_products'):
                        tables_to_wipe.extend(['Products', 'Product_Catalog', 'Products_Master'])
                        wiped_categories.append("Retail Finished Products Master Catalog")
                    
                    if not tables_to_wipe:
                        feedback_msg = "❌ Maintenance Notice: Deletion sweep aborted because no data components were selected."
                        alert_type = "danger"
                        conn.close()
                    else:
                        for table in tables_to_wipe:
                            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
                            if cursor.fetchone():
                                cursor.execute(f"DELETE FROM {table}")
                        
                        # 🔥 FIX: Commit the deletions to terminate active transaction state cleanly
                        conn.commit()
                        
                        # 🔥 FIX: Temporarily isolate the database state to autocommit mode to run defragmentation
                        conn.isolation_level = None
                        cursor.execute("VACUUM")
                        
                        conn.close()
                        
                        feedback_msg = f"⚠️ Targeted Clean Sweep Complete: Cleared records from selected sectors: {', '.join(wiped_categories)}."
                        alert_type = "warning"
                except Exception as e:
                    feedback_msg = f"❌ Maintenance Error pruning target schema configurations: {str(e)}"
                    alert_type = "danger"
            else:
                feedback_msg = "❌ Safety Cancel: Database reset aborted. You must type the keyword 'RESET' exactly to clear storage tables."
                alert_type = "danger"

        return redirect(f"/portal/{username}/settings?msg={feedback_msg}&alert_type={alert_type}")

    # ==========================================
    # 📤 2. GET METHOD: EXTRACT ROSTER DATA
    # ==========================================
    conn = sqlite3.connect(client_db_path)
    staff_df = pd.read_sql("SELECT * FROM Staff_Accounts", conn)
    conn.close()
    
    staff_list = staff_df.to_dict(orient='records') if not staff_df.empty else []

    return render_template(
        'settings.html', 
        username=username, 
        msg=request.args.get('msg', feedback_msg),
        alert_type=request.args.get('alert_type', alert_type),
        staff_members=staff_list
    )