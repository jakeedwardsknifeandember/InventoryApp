# routes/auth.py - Multi-Role Authentication Engine
from flask import Blueprint, render_template, request, redirect, session, flash
import sqlite3
import os

auth_bp = Blueprint('auth', __name__)

USER_DB_PATH = "data/users.db"

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        staff_username = request.form.get('staff_username', '').strip().lower()
        password = request.form.get('password', '').strip()
        login_role = request.form.get('login_type', 'owner').strip()

        if not username or not password:
            flash('Please enter all required login details.', 'danger')
            return render_template('login.html', username=username, staff_username=staff_username, active_tab=login_role)

        if login_role == 'owner':
            # 👑 BUSINESS OWNER LOGIN
            conn = sqlite3.connect(USER_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT username, password FROM users WHERE LOWER(username) = ?", (username,))
            user = cursor.fetchone()
            conn.close()

            if user and user[1] == password:
                session['logged_in_user'] = username
                session['staff_role'] = 'Platform Owner Admin'
                return redirect(f"/portal/{username}")
            else:
                flash('Invalid Business Owner credentials supplied.', 'danger')
                return render_template('login.html', username=username, active_tab='owner')

        else:
            # 🍳 KITCHEN TERMINAL LOGIN
            
            # 1. Verify Store Name exists in users.db
            conn = sqlite3.connect(USER_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT username, password FROM users WHERE LOWER(username) = ?", (username,))
            store_record = cursor.fetchone()
            conn.close()

            if not store_record:
                flash('Store account not found. Please check the Store Name.', 'danger')
                return render_template('login.html', username=username, staff_username=staff_username, active_tab='kitchen')

            store_name = store_record[0].lower()
            master_pass = store_record[1]

            client_db = f"data/client_{store_name}.db"

            # 2. Check if logging in directly to tenant database
            if os.path.exists(client_db):
                conn = sqlite3.connect(client_db)
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
                
                # Search by Staff Username + Password
                if staff_username:
                    cursor.execute(
                        "SELECT Role FROM Staff_Accounts WHERE LOWER(Username) = ? AND Password = ? AND Active = 'Yes'",
                        (staff_username, password)
                    )
                else:
                    cursor.execute(
                        "SELECT Role FROM Staff_Accounts WHERE Password = ? AND Active = 'Yes'",
                        (password,)
                    )
                    
                row = cursor.fetchone()
                conn.close()

                if row:
                    session['logged_in_user'] = store_name
                    session['staff_role'] = row[0]
                    return redirect(f"/portal/{store_name}")

            # 3. Fallback: Owner using master store password on Kitchen Terminal
            if password == master_pass:
                session['logged_in_user'] = store_name
                session['staff_role'] = 'Barista / Kitchen Crew'
                return redirect(f"/portal/{store_name}")

            flash('Invalid Kitchen Terminal credentials supplied.', 'danger')
            return render_template('login.html', username=username, staff_username=staff_username, active_tab='kitchen')

    return render_template('login.html', active_tab='owner')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')