# routes/settings.py - Settings Module Blueprint
from flask import Blueprint, request, redirect, session, render_template
import sqlite3

settings_bp = Blueprint('settings', __name__)

USER_DB_PATH = "data/users.db"

@settings_bp.route('/portal/<username>/settings', methods=['GET', 'POST'])
def web_settings_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    feedback_msg = None
    if request.method == 'POST' and request.form.get('action_type') == 'change_password':
        old_p, new_p = request.form.get('old_password'), request.form.get('new_password')
        conn = sqlite3.connect(USER_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
        record = cursor.fetchone()
        
        if record and old_p == record[0]:
            cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_p, username))
            conn.commit()
            feedback_msg = "✅ Success: Your portal password has been updated!"
        else: 
            feedback_msg = "❌ Error: The current password you entered is incorrect."
        conn.close()
        
    return render_template('settings.html', username=username, msg=feedback_msg)