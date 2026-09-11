# routes/settings.py - Enterprise Settings Engine with Multi-Entity CSV Sync, Backup & Restore
from flask import Blueprint, request, redirect, session, render_template, send_file
from modules.database import InventoryDB
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
    client_db = InventoryDB(client_db_path)
    
    feedback_msg = None
    alert_type = "success"

    if request.method == 'POST':
        action = request.form.get('action_type')
        
        # 1. CHANGE MASTER PASSWORD
        if action == 'change_password':
            old_p = request.form.get('old_password')
            new_p = request.form.get('new_password')
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

        # 2. ADD STAFF SUB-ACCOUNT
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

        # 3. RESET STAFF PASSWORD
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

        # 4. DELETE STAFF ACCOUNT
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

        # 5. BACKUP DATABASE FILE
        elif action == 'backup_database':
            try:
                date_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                return send_file(
                    client_db_path,
                    as_attachment=True,
                    download_name=f"matrix_backup_{username}_{date_stamp}.db"
                )
            except Exception as e:
                feedback_msg = f"Error executing file packaging: {str(e)}"
                alert_type = "danger"

        # 6. RESTORE DATABASE FILE
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

        # 7. BULK CSV IMPORT (INGREDIENTS, PRODUCTS, AND RECIPES)
        elif action == 'bulk_import':
            target_table = request.form.get('import_target')
            uploaded_file = request.files.get('csv_file')
            
            if not uploaded_file or uploaded_file.filename == '':
                feedback_msg = "Error: No CSV file attached for upload."
                alert_type = "danger"
            else:
                try:
                    stream = io.StringIO(uploaded_file.stream.read().decode("utf-8-sig"), newline=None)
                    df = pd.read_csv(stream)
                    
                    conn = sqlite3.connect(client_db_path, timeout=20.0)

                    # ===== SCENARIO A: RECIPES IMPORT =====
                    if target_table == 'recipes':
                        col_map = {str(col).lower().strip().replace(' ', '_'): col for col in df.columns}
                        
                        pid_col = col_map.get('product_id') or col_map.get('prod_id')
                        pname_col = col_map.get('product_name') or col_map.get('product') or col_map.get('name')
                        iid_col = col_map.get('ingredient_id') or col_map.get('ing_id')
                        iname_col = col_map.get('ingredient_name') or col_map.get('ingredient') or col_map.get('item_name')
                        qty_col = col_map.get('quantity_required') or col_map.get('quantity') or col_map.get('qty') or col_map.get('amount')
                        unit_col = col_map.get('unit') or col_map.get('uom')

                        products_db = pd.read_sql("SELECT Product_ID, Product_Name FROM Products", conn)
                        ingredients_db = pd.read_sql("SELECT Ingredient_ID, Ingredient_Name, Unit FROM Ingredients", conn)

                        valid_prod_ids = set(products_db['Product_ID'].astype(str).str.strip())
                        prod_name_to_id = {str(n).strip().lower(): str(pid).strip() for pid, n in zip(products_db['Product_ID'], products_db['Product_Name']) if pd.notna(n)}

                        valid_ing_ids = set(ingredients_db['Ingredient_ID'].astype(str).str.strip())
                        ing_name_to_id = {str(n).strip().lower(): str(iid).strip() for iid, n in zip(ingredients_db['Ingredient_ID'], ingredients_db['Ingredient_Name']) if pd.notna(n)}
                        ing_id_to_default_unit = {str(iid).strip(): str(u).strip() for iid, u in zip(ingredients_db['Ingredient_ID'], ingredients_db['Unit']) if pd.notna(u)}

                        recipes_by_product = {}
                        skipped_rows = []

                        for row_idx, row in df.iterrows():
                            raw_pid = str(row[pid_col]).strip() if pid_col and pd.notna(row.get(pid_col)) else ""
                            raw_pname = str(row[pname_col]).strip() if pname_col and pd.notna(row.get(pname_col)) else ""
                            
                            resolved_pid = None
                            if raw_pid and raw_pid in valid_prod_ids:
                                resolved_pid = raw_pid
                            elif raw_pname and raw_pname.lower() in prod_name_to_id:
                                resolved_pid = prod_name_to_id[raw_pname.lower()]
                            elif raw_pid and raw_pid.lower() in prod_name_to_id:
                                resolved_pid = prod_name_to_id[raw_pid.lower()]

                            if not resolved_pid:
                                skipped_rows.append(f"Row {row_idx+2}: Unknown Product '{raw_pid or raw_pname}'")
                                continue

                            raw_iid = str(row[iid_col]).strip() if iid_col and pd.notna(row.get(iid_col)) else ""
                            raw_iname = str(row[iname_col]).strip() if iname_col and pd.notna(row.get(iname_col)) else ""
                            
                            resolved_iid = None
                            if raw_iid and raw_iid in valid_ing_ids:
                                resolved_iid = raw_iid
                            elif raw_iname and raw_iname.lower() in ing_name_to_id:
                                resolved_iid = ing_name_to_id[raw_iname.lower()]
                            elif raw_iid and raw_iid.lower() in ing_name_to_id:
                                resolved_iid = ing_name_to_id[raw_iid.lower()]

                            if not resolved_iid:
                                skipped_rows.append(f"Row {row_idx+2}: Unknown Ingredient '{raw_iid or raw_iname}'")
                                continue

                            try:
                                qty_val = float(row[qty_col]) if qty_col and pd.notna(row.get(qty_col)) else 0.0
                            except (ValueError, TypeError):
                                qty_val = 0.0

                            if qty_val <= 0:
                                skipped_rows.append(f"Row {row_idx+2}: Invalid quantity for {resolved_pid}")
                                continue

                            unit_val = str(row[unit_col]).strip() if unit_col and pd.notna(row.get(unit_col)) else ing_id_to_default_unit.get(resolved_iid, 'pcs')

                            # Normalize grams and milliliters into base inventory units
                            stored_qty = qty_val

                            if resolved_pid not in recipes_by_product:
                                recipes_by_product[resolved_pid] = []

                            recipes_by_product[resolved_pid].append({
                                'ingredient_id': resolved_iid,
                                'quantity': stored_qty,
                                'unit': unit_val
                            })

                        if recipes_by_product:
                            existing_recipes = pd.read_sql("SELECT * FROM Recipes", conn)
                            updated_pids = list(recipes_by_product.keys())
                            
                            if not existing_recipes.empty:
                                existing_recipes = existing_recipes[~existing_recipes['Product_ID'].isin(updated_pids)]

                            new_rows = []
                            total_lines = 0
                            for pid, items in recipes_by_product.items():
                                for idx, item in enumerate(items, start=1):
                                    new_rows.append({
                                        'Recipe_ID': f"{pid}-REC{idx:03d}",
                                        'Product_ID': pid,
                                        'Ingredient_ID': item['ingredient_id'],
                                        'Quantity_Required': item['quantity'],
                                        'Unit': item['unit']
                                    })
                                    total_lines += 1

                            combined_recipes = pd.concat([existing_recipes, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else existing_recipes
                            combined_recipes.to_sql('Recipes', conn, if_exists='replace', index=False)
                            conn.commit()
                            conn.close()

                            client_db.update_all_product_costs()
                            client_db.log_user_action(
                                username=username,
                                action_type="BULK_IMPORT_RECIPES",
                                module="Recipes",
                                details=f"Bulk imported recipe matrices for {len(recipes_by_product)} products ({total_lines} lines)"
                            )

                            feedback_msg = f"Success: Successfully imported recipes for {len(recipes_by_product)} products ({total_lines} recipe components). Food costs and margins recalculated."
                            if skipped_rows:
                                feedback_msg += f" Note: {len(skipped_rows)} rows skipped due to invalid product/ingredient names."
                            alert_type = "success"
                        else:
                            conn.close()
                            feedback_msg = "Error: No valid recipe rows found in CSV. Please verify that your Product and Ingredient names or IDs match existing catalog records."
                            alert_type = "danger"

                    # ===== SCENARIO B: INGREDIENTS OR PRODUCTS IMPORT =====
                    else:
                        cursor = conn.cursor()
                        target_table_name = 'Ingredients' if target_table == 'ingredients' else 'Products'
                        id_col = 'Ingredient_ID' if target_table == 'ingredients' else 'Product_ID'
                        name_col = 'Ingredient_Name' if target_table == 'ingredients' else 'Product_Name'
                        prefix = "ING" if target_table == 'ingredients' else "PROD"
                        
                        cursor.execute(f"PRAGMA table_info({target_table_name})")
                        valid_cols = [row[1] for row in cursor.fetchall()]
                        
                        # Automated database deduplication sweep
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
                        
                        for _, row in df.iterrows():
                            row_dict = {k: v for k, v in row.items() if pd.notna(v)}
                            
                            name_val = str(row_dict.get(name_col, '')).strip()
                            if not name_val or name_val.lower() == 'nan': 
                                continue
                            
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
                        
                        client_db.update_all_product_costs()
                        feedback_msg = f"Success: Bulk synced {processed_count} records into the {target_table_name} database."
                        alert_type = "success"
                    
                except Exception as e:
                    feedback_msg = f"CSV Format Error: {str(e)}"
                    alert_type = "danger"

        # 8. DOWNLOAD CSV TEMPLATE
        elif action == 'download_template':
            template_type = request.form.get('template_type')
            
            try:
                conn = sqlite3.connect(client_db_path)
                if template_type == 'recipes':
                    df = pd.DataFrame(columns=[
                        'Product_ID', 'Product_Name', 'Ingredient_ID', 'Ingredient_Name', 'Quantity_Required', 'Unit'
                    ])
                elif template_type == 'ingredients':
                    df = pd.read_sql("SELECT * FROM Ingredients LIMIT 0", conn)
                else:
                    df = pd.read_sql("SELECT * FROM Products LIMIT 0", conn)
                conn.close()
                
                buffer = io.BytesIO()
                df.to_csv(buffer, index=False, encoding='utf-8')
                buffer.seek(0)
                filename = f"template_{template_type}_{username}.csv"
                return send_file(buffer, as_attachment=True, download_name=filename, mimetype='text/csv')
            except Exception as e:
                feedback_msg = f"Template Generation Error: {str(e)}"
                alert_type = "danger"

        # 9. EXPORT CSV DATA (CORRECTED ROUTING FOR RECIPES)
        elif action == 'export_csv':
            export_target = request.form.get('export_target')
            
            try:
                conn = sqlite3.connect(client_db_path)
                if export_target == 'recipes':
                    query = """
                        SELECT 
                            r.Product_ID,
                            COALESCE(p.Product_Name, r.Product_ID) AS Product_Name,
                            r.Ingredient_ID,
                            COALESCE(i.Ingredient_Name, r.Ingredient_ID) AS Ingredient_Name,
                            r.Quantity_Required,
                            r.Unit
                        FROM Recipes r
                        LEFT JOIN Products p ON r.Product_ID = p.Product_ID
                        LEFT JOIN Ingredients i ON r.Ingredient_ID = i.Ingredient_ID
                        ORDER BY r.Product_ID, r.Ingredient_ID
                    """
                    df = pd.read_sql(query, conn)
                    conn.close()
                    
                    if not df.empty and 'Quantity_Required' in df.columns:
                        df['Quantity_Required'] = pd.to_numeric(df['Quantity_Required'], errors='coerce').fillna(0.0)
                        mask = df['Unit'].astype(str).str.lower().str.strip().isin(['g', 'ml'])
                        df.loc[mask, 'Quantity_Required'] = (df.loc[mask, 'Quantity_Required'] * 1000.0).round(4)
                elif export_target == 'ingredients':
                    df = pd.read_sql("SELECT * FROM Ingredients", conn)
                    conn.close()
                else:
                    df = pd.read_sql("SELECT * FROM Products", conn)
                    conn.close()
                
                buffer = io.BytesIO()
                df.to_csv(buffer, index=False, encoding='utf-8')
                buffer.seek(0)
                filename = f"export_{export_target}_{username}_{datetime.now().strftime('%Y%m%d')}.csv"
                return send_file(buffer, as_attachment=True, download_name=filename, mimetype='text/csv')
            except Exception as e:
                feedback_msg = f"Export Error: {str(e)}"
                alert_type = "danger"

        # 10. SELECTIVE RESET
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
                        tables_to_wipe.extend(['Recipes', 'Prep_Recipes'])
                        wiped_categories.append("Linked Product Recipes")
                        
                    if request.form.get('wipe_ingredients'):
                        tables_to_wipe.extend(['Ingredients'])
                        wiped_categories.append("Raw Material Ingredients List")
                        
                    if request.form.get('wipe_products'):
                        tables_to_wipe.extend(['Products'])
                        wiped_categories.append("Retail Finished Menu Product Catalogs")
                    
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
                        
                        client_db.update_all_product_costs()
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