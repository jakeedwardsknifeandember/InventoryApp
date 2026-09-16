# routes/auth.py - Multi-Role Authentication & Smart POS Dispatcher
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
            # BUSINESS OWNER / ADMINISTRATOR LOGIN
            conn = sqlite3.connect(USER_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT username, password FROM users WHERE LOWER(username) = ?", (username,))
            user = cursor.fetchone()
            conn.close()

            if user and user[1] == password:
                session['logged_in_user'] = username
                session['staff_role'] = 'Platform Owner Admin'
                session['staff_username'] = username.title()
                return redirect(f"/portal/{username}")
            else:
                flash('Invalid Business Owner credentials supplied.', 'danger')
                return render_template('login.html', username=username, active_tab='owner')

        else:
            # COUNTER STAFF / KITCHEN CREW LOGIN
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

            # Check tenant Staff_Accounts registry
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

                if staff_username:
                    cursor.execute(
                        "SELECT Role, Username FROM Staff_Accounts WHERE LOWER(Username) = ? AND Password = ? AND Active = 'Yes'",
                        (staff_username, password)
                    )
                else:
                    cursor.execute(
                        "SELECT Role, Username FROM Staff_Accounts WHERE Password = ? AND Active = 'Yes'",
                        (password,)
                    )

                row = cursor.fetchone()
                conn.close()

                if row:
                    staff_role = row[0]
                    actual_staff_name = row[1] if row[1] else (staff_username or 'Counter Staff')

                    session['logged_in_user'] = store_name
                    session['staff_role'] = staff_role
                    session['staff_username'] = actual_staff_name.title()

                    # Smart RBAC Routing: Managers/Owners access the Back-of-House Portal, Crew goes strictly to Live POS
                    if staff_role in ['Platform Owner Admin', 'Store Manager']:
                        return redirect(f"/portal/{store_name}")
                    else:
                        return redirect(f"/portal/{store_name}/pos")

            # Fallback: Owner using master store password on terminal
            if password == master_pass:
                session['logged_in_user'] = store_name
                session['staff_role'] = 'Barista / Kitchen Crew'
                session['staff_username'] = 'Floor Staff'
                return redirect(f"/portal/{store_name}/pos")

            flash('Invalid Staff Terminal credentials supplied.', 'danger')
            return render_template('login.html', username=username, staff_username=staff_username, active_tab='kitchen')

    return render_template('login.html', active_tab='owner')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')