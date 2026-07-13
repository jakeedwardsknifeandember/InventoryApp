# routes/auth.py - Dedicated Authentication & Access Blueprint Engine
from flask import Blueprint, request, redirect, session, render_template
import sqlite3
import os

auth_bp = Blueprint('auth', __name__)

USER_DB_PATH = "data/users.db"

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        login_type = request.form.get('login_type', 'owner')
        tenant_company = request.form.get('username', '').lower().strip()
        password = request.form.get('password', '')
        
        # 👑 SCENARIO A: AUTHENTICATE MASTER BUSINESS OWNER
        if login_type == 'owner':
            conn = sqlite3.connect(USER_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT password FROM users WHERE username = ?", (tenant_company,))
            record = cursor.fetchone()
            conn.close()
            
            if record and record[0] == password:
                session['logged_in_user'] = tenant_company
                session['staff_user'] = tenant_company
                session['staff_role'] = 'Platform Owner Admin'
                return redirect(f'/portal/{tenant_company}')
            else:
                error = "Invalid master owner company credentials."
        
        # 👥 SCENARIO B: AUTHENTICATE TEAM MEMBER (MANAGER / CREW)
        else:
            staff_user = request.form.get('staff_username', '').lower().strip()
            client_db_path = f"data/client_{tenant_company}.db"
            
            if not os.path.exists(client_db_path):
                error = f"Store database code '{tenant_company}' does not exist."
            else:
                conn = sqlite3.connect(client_db_path)
                cursor = conn.cursor()
                
                # Check to see if staff registry exists inside sqlite metadata
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Staff_Accounts'")
                if not cursor.fetchone():
                    conn.close()
                    error = "No staff accounts provisioned for this store location."
                else:
                    cursor.execute("SELECT Password, Role FROM Staff_Accounts WHERE Username = ?", (staff_user,))
                    record = cursor.fetchone()
                    conn.close()
                    
                    if record and record[0] == password:
                        session['logged_in_user'] = tenant_company  # Safe file resolution tracking
                        session['staff_user'] = staff_user
                        session['staff_role'] = record[1]          # Grant RBAC permissions key token
                        return redirect(f'/portal/{tenant_company}')
                    else:
                        error = "Invalid staff user credentials or access passkey."
                        
    return render_template('login.html', error=error)

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')