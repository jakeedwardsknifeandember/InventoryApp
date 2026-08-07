# routes/settings.py - Advanced Enterprise Settings Module with Dynamic Backup & Restore Matrix
from flask import Blueprint, request, redirect, session, render_template, send_file
import sqlite3
import pandas as pd
from datetime import datetime
import os
import io

settings_bp = Blueprint('settings', __name__)

USER_DB_PATH = "data/users.db"

def ensure_staff_table_exists(client_db_path):
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
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    if not session.get('staff_role') and session.get('logged_in_user') == username:
        session['staff_role'] = 'Platform Owner Admin'
        
    active_role = session.get('staff_role', 'Barista / Kitchen Crew')
    if active_role != 'Platform Owner Admin':
        return redirect(f"/portal/{username}?error=Access Denied: Administrative Settings panel is strictly reserved for the Master Platform Owner Admin.")
        
    client_db_path = f"data/client_{username}.db"
    ensure_staff_table_exists(client_db_path)
    
    feedback_msg = None
    alert_type = "success"

    if request.method == 'POST':
        action = request.form.get('action_type')
        
        if action == 'change_password':
            old_p, new_p = request.form.get('old_password'), request.form.get('new_password')
            conn = sqlite3.connect(USER_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
            record = cursor.fetchone()
            
            if record and old_p == record[0]:
                cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_p, username))
                conn.commit()
                feedback_msg = "Success: Master portal login password updated successfully."
                alert_type = "success"
            else: 
                feedback_msg = "Error: The current password you entered is incorrect."
                alert_type = "danger"
            conn.close()

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
                    feedback_msg = f"Success: Created sub-account for crew member '{staff_user.capitalize()}' as {staff_role}."
                    alert_type = "success"
                except sqlite3.IntegrityError:
                    feedback_msg = f"Error: A team sub-account named '{staff_user}' is already registered."
                    alert_type = "danger"
                conn.close()

        elif action == 'reset_staff_password':
            staff_id = request.form.get('staff_id')
            new_pass = request.form.get('new_password', '').strip()
            
            if staff_id and new_pass:
                conn = sqlite3.connect(client_db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE Staff_Accounts SET Password = ? WHERE Staff_ID = ?", (new_pass, staff_id))
                conn.commit()
                conn.close()
                feedback_msg = "Security Override: Staff access token passkey reassigned successfully."
                alert_type = "success"

        elif action == 'delete_staff':
            staff_id = request.form.get('staff_id')
            if staff_id:
                conn = sqlite3.connect(client_db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM Staff_Accounts WHERE Staff_ID = ?", (staff_id,))
                conn.commit()
                conn.close()
                feedback_msg = "Access terminated: Crew token stripped from active registers cleanly."
                alert_type = "warning"

        elif action == 'backup_database':
            try:
                date_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                return send_file(
                    client_db_path,
                    as_attachment=True,
                    download_name=f"matrix_backup_{username}_{date_stamp}.db"
                )
            except Exception as e:
                feedback_msg = f"Error executing file package packaging: {str(e)}"
                alert_type = "danger"

        elif action == 'restore_database':
            uploaded_file = request.files.get('backup_file')
            if not uploaded_file or uploaded_file.filename == '':
                feedback_msg = "Error: No database backup archive file selected for transmission."
                alert_type = "danger"
            elif not uploaded_file.filename.endswith('.db'):
                feedback_msg = "Error Security Violation: Invalid payload file format. The system only accepts valid operational SQLite .db assets."
                alert_type = "danger"
            else:
                try:
                    uploaded_file.save(client_db_path)
                    feedback_msg = "System Restoration Successful: The database file has been successfully hot-swapped."
                    alert_type = "success"
                except Exception as e:
                    feedback_msg = f"Restoration Fault during file overwrite sequencing: {str(e)}"
                    alert_type = "danger"

        # DYNAMIC BULK CSV DATA IMPORTER WITH SELF-HEALING DEDUPLICATION
        elif action == 'bulk_import':
            target_table = request.form.get('import_target')
            uploaded_file = request.files.get('csv_file')
            
            if not uploaded_file or uploaded_file.filename == '':
                feedback_msg = "Error: No CSV file attached for upload."
                alert_type = "danger"
            else:
                try:
                    stream = io.StringIO(uploaded_file.stream.read().decode("UTF8"), newline=None)
                    df = pd.read_csv(stream)
                    
                    conn = sqlite3.connect(client_db_path, timeout=20.0)
                    cursor = conn.cursor()
                    
                    target_table_name = 'Ingredients' if target_table == 'ingredients' else 'Products'
                    id_col = 'Ingredient_ID' if target_table == 'ingredients' else 'Product_ID'
                    name_col = 'Ingredient_Name' if target_table == 'ingredients' else 'Product_Name'
                    prefix = "ING" if target_table == 'ingredients' else "PROD"
                    
                    cursor.execute(f"PRAGMA table_info({target_table_name})")
                    valid_cols = [row[1] for row in cursor.fetchall()]
                    
                    # PHASE 1: AUTOMATIC DATABASE DEDUPLICATION SWEEP
                    # This permanently deletes cloned rows caused by older scripts before processing new data
                    cursor.execute(f"""
                        DELETE FROM {target_table_name}
                        WHERE rowid NOT IN (
                            SELECT MIN(rowid)
                            FROM {target_table_name}
                            GROUP BY {id_col}
                        )
                    """)
                    conn.commit()
                    
                    processed_count = 0
                    
                    # PHASE 2: SEAMLESS DATA SYNC
                    for _, row in df.iterrows():
                        row_dict = {k: v for k, v in row.items() if pd.notna(v)}
                        
                        name_val = str(row_dict.get(name_col, '')).strip()
                        if not name_val or name_val.lower() == 'nan': continue
                        
                        item_id = str(row_dict.get(id_col, '')).strip()
                        
                        if not item_id or item_id.lower() in ['nan', 'none', 'null', '']:
                            cursor.execute(f"SELECT {id_col} FROM {target_table_name} WHERE {name_col} = ?", (name_val,))
                            name_match = cursor.fetchone()
                            
                            if name_match:
                                item_id = name_match[0]
                                row_dict[id_col] = item_id
                            else:
                                cursor.execute(f"SELECT {id_col} FROM {target_table_name} WHERE {id_col} LIKE '{prefix}%'")
                                existing_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
                                nums = []
                                for eid in existing_ids:
                                    try:
                                        nums.append(int(eid.replace(prefix, '')))
                                    except ValueError:
                                        pass
                                next_num = max(nums) + 1 if nums else 1
                                item_id = f"{prefix}{next_num:04d}"
                                row_dict[id_col] = item_id
                                
                        insert_data = {k: v for k, v in row_dict.items() if k in valid_cols}
                        
                        cursor.execute(f"SELECT COUNT(*) FROM {target_table_name} WHERE {id_col} = ?", (item_id,))
                        exists = cursor.fetchone()[0] > 0
                        
                        if exists:
                            update_cols = [k for k in insert_data.keys() if k != id_col]
                            if update_cols:
                                set_clause = ", ".join([f"{k} = ?" for k in update_cols])
                                update_values = tuple([insert_data[k] for k in update_cols] + [item_id])
                                cursor.execute(f"UPDATE {target_table_name} SET {set_clause} WHERE {id_col} = ?", update_values)
                        else:
                            cols = ", ".join(insert_data.keys())
                            placeholders = ", ".join(["?"] * len(insert_data))
                            values = tuple(insert_data.values())
                            cursor.execute(f"INSERT INTO {target_table_name} ({cols}) VALUES ({placeholders})", values)
                            
                        processed_count += 1
                    
                    conn.commit()
                    conn.close()
                    
                    feedback_msg = f"Success: Bulk synced {processed_count} records into the {target_table_name} database."
                    alert_type = "success"
                    
                except Exception as e:
                    feedback_msg = f"CSV Format Error: {str(e)}"
                    alert_type = "danger"

        elif action == 'download_template':
            template_type = request.form.get('template_type')
            table_name = 'Ingredients' if template_type == 'ingredients' else 'Products'
            
            try:
                conn = sqlite3.connect(client_db_path)
                df = pd.read_sql(f"SELECT * FROM {table_name} LIMIT 0", conn)
                conn.close()
                
                buffer = io.BytesIO()
                df.to_csv(buffer, index=False, encoding='utf-8')
                buffer.seek(0)
                filename = f"template_{template_type}_{username}.csv"
                return send_file(buffer, as_attachment=True, download_name=filename, mimetype='text/csv')
            except Exception as e:
                feedback_msg = f"Template Generation Error: {str(e)}"
                alert_type = "danger"

        elif action == 'export_csv':
            export_target = request.form.get('export_target')
            table_name = 'Ingredients' if export_target == 'ingredients' else 'Products'
            
            try:
                conn = sqlite3.connect(client_db_path)
                df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
                conn.close()
                
                buffer = io.BytesIO()
                df.to_csv(buffer, index=False, encoding='utf-8')
                buffer.seek(0)
                filename = f"export_{export_target}_{username}_{datetime.now().strftime('%Y%m%d')}.csv"
                return send_file(buffer, as_attachment=True, download_name=filename, mimetype='text/csv')
            except Exception as e:
                feedback_msg = f"Export Error: {str(e)}"
                alert_type = "danger"

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
                        feedback_msg = "Maintenance Notice: Deletion sweep aborted because no data components were selected."
                        alert_type = "danger"
                        conn.close()
                    else:
                        for table in tables_to_wipe:
                            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
                            if cursor.fetchone():
                                cursor.execute(f"DELETE FROM {table}")
                        
                        conn.commit()
                        conn.isolation_level = None
                        cursor.execute("VACUUM")
                        conn.close()
                        
                        feedback_msg = f"Targeted Clean Sweep Complete: Cleared records from selected sectors: {', '.join(wiped_categories)}."
                        alert_type = "warning"
                except Exception as e:
                    feedback_msg = f"Maintenance Error pruning target schema configurations: {str(e)}"
                    alert_type = "danger"
            else:
                feedback_msg = "Safety Cancel: Database reset aborted. You must type the keyword 'RESET' exactly to clear storage tables."
                alert_type = "danger"

        return redirect(f"/portal/{username}/settings?msg={feedback_msg}&alert_type={alert_type}")

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