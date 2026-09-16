# routes/settings.py - Enterprise Settings Engine with Multi-Encoding CSV Sync, Token-Sorted Key Matching & Integrity Guard
from flask import Blueprint, request, redirect, session, render_template, send_file
from modules.database import InventoryDB
import sqlite3
import pandas as pd
from datetime import datetime
import os
import io
import re

settings_bp = Blueprint('settings', __name__)

USER_DB_PATH = "data/users.db"

def normalize_text_key(text):
    """Normalizes string by removing punctuation, brackets, dashes, and collapsing multiple spaces."""
    if not text or pd.isna(text):
        return ""
    s = str(text).strip().lower()
    s = re.sub(r'[\-_–—\(\)\[\]:/\\,]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def token_sorted_key(text):
    """
    Bag-of-words token-sorted key.
    Resolves word inversions automatically:
      'Onion White' -> 'onion white'
      'White Onion' -> 'onion white'
      'Hot - Americano Coffee' -> 'americano coffee hot'
    """
    norm = normalize_text_key(text)
    if not norm:
        return ""
    return " ".join(sorted(norm.split()))

def alphanumeric_text_key(text):
    """Strict alphanumeric key that strips all whitespace and punctuation."""
    if not text or pd.isna(text):
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', str(text).lower())

def build_entity_resolver(id_name_pairs):
    """
    Constructs a multi-stage entity resolver supporting exact ID, exact name,
    normalized spacing, bag-of-words token sorting, and alphanumeric matching.
    """
    valid_ids = set()
    exact_map = {}
    norm_map = {}
    token_map = {}
    alpha_map = {}

    for item_id, name in id_name_pairs:
        if not item_id or pd.isna(item_id):
            continue
        iid = str(item_id).strip()
        valid_ids.add(iid)
        if name and pd.notna(name):
            n = str(name).strip()
            exact_map[n.lower()] = iid
            norm_map[normalize_text_key(n)] = iid
            token_map[token_sorted_key(n)] = iid
            alpha_map[alphanumeric_text_key(n)] = iid

    def resolve(val_id, val_name):
        if val_id and pd.notna(val_id):
            v_id_str = str(val_id).strip()
            if v_id_str in valid_ids:
                return v_id_str

        for cand in [val_id, val_name]:
            if not cand or pd.isna(cand):
                continue
            c = str(cand).strip()
            if not c:
                continue
            c_low = c.lower()
            if c_low in exact_map:
                return exact_map[c_low]
            c_norm = normalize_text_key(c)
            if c_norm in norm_map:
                return norm_map[c_norm]
            c_token = token_sorted_key(c)
            if c_token in token_map:
                return token_map[c_token]
            c_alpha = alphanumeric_text_key(c)
            if c_alpha in alpha_map:
                return alpha_map[c_alpha]

        return None

    return valid_ids, resolve

def ensure_store_settings_exist(client_db_path):
    """Ensures the Store_Settings key-value configuration table exists with defaults."""
    conn = sqlite3.connect(client_db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Store_Settings (
            Setting_Key TEXT PRIMARY KEY,
            Setting_Value TEXT
        )
    """)
    default_settings = {
        'enforce_blind_count': 'yes',
        'variance_alert_pct': '2.0',
        'variance_alert_value': '100.0'
    }
    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO Store_Settings (Setting_Key, Setting_Value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

def get_store_settings(client_db_path):
    """Retrieves store governance and operational policies dictionary."""
    ensure_store_settings_exist(client_db_path)
    conn = sqlite3.connect(client_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT Setting_Key, Setting_Value FROM Store_Settings")
    settings_dict = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return settings_dict

def ensure_staff_table_exists(client_db_path):
    """Ensures Staff_Accounts table exists and migrates Full_Name, Display_Name, and PIN columns if missing."""
    conn = sqlite3.connect(client_db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Staff_Accounts (
            Staff_ID TEXT PRIMARY KEY,
            Full_Name TEXT,
            Display_Name TEXT,
            Username TEXT UNIQUE,
            Password TEXT,
            PIN TEXT,
            Role TEXT,
            Active TEXT DEFAULT 'Yes'
        )
    """)
    cursor.execute("PRAGMA table_info(Staff_Accounts)")
    existing_cols = [col[1] for col in cursor.fetchall()]
    if 'Full_Name' not in existing_cols:
        cursor.execute("ALTER TABLE Staff_Accounts ADD COLUMN Full_Name TEXT DEFAULT ''")
    if 'Display_Name' not in existing_cols:
        cursor.execute("ALTER TABLE Staff_Accounts ADD COLUMN Display_Name TEXT DEFAULT ''")
    if 'PIN' not in existing_cols:
        cursor.execute("ALTER TABLE Staff_Accounts ADD COLUMN PIN TEXT DEFAULT '1234'")

    conn.commit()
    conn.close()

def heal_database_integrity(conn):
    """
    Guarantees structural integrity across recipes, types, and mathematical pricing:
    1. Restores prepped items missing from the Ingredients table.
    2. Reasserts PREPPED status for items defined in Prep_Recipes.
    3. Enforces Cost_Per_Unit = Purchase_Cost / Pack_Size for all RAW wholesale goods.
    """
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT Prepped_Ingredient_ID FROM Prep_Recipes
            WHERE Prepped_Ingredient_ID NOT IN (SELECT Ingredient_ID FROM Ingredients)
        """)
        orphaned_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
        for orphan_id in orphaned_ids:
            cursor.execute("""
                INSERT INTO Ingredients (
                    Ingredient_ID, Ingredient_Name, Unit, Category, 
                    Ingredient_Type, Active, Current_Stock, Min_Stock, Cost_Per_Unit
                ) VALUES (?, ?, 'g', 'Prep', 'PREPPED', 'Yes', 0.0, 0.0, 0.0)
            """, (orphan_id, orphan_id))

        cursor.execute("""
            UPDATE Ingredients 
            SET Ingredient_Type = 'PREPPED'
            WHERE Ingredient_ID IN (SELECT DISTINCT Prepped_Ingredient_ID FROM Prep_Recipes)
        """)

        cursor.execute("""
            UPDATE Ingredients
            SET Cost_Per_Unit = ROUND(Purchase_Cost / Pack_Size, 4)
            WHERE (Ingredient_Type IS NULL OR UPPER(Ingredient_Type) = 'RAW')
              AND Purchase_Cost > 0 
              AND Pack_Size > 0
              AND (
                  Cost_Per_Unit IS NULL 
                  OR Cost_Per_Unit <= 0 
                  OR ABS(Cost_Per_Unit - (Purchase_Cost / Pack_Size)) > 0.0001
              )
        """)

        cursor.execute("""
            UPDATE Ingredients
            SET Purchase_Cost = ROUND(Cost_Per_Unit * Pack_Size, 2)
            WHERE (Ingredient_Type IS NULL OR UPPER(Ingredient_Type) = 'RAW')
              AND Cost_Per_Unit > 0
              AND (Purchase_Cost IS NULL OR Purchase_Cost <= 0)
              AND Pack_Size > 0
        """)

        conn.commit()
    except Exception as e:
        print(f"Database healing warning: {e}")

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

        # 2. ADD STAFF SUB-ACCOUNT WITH IDENTITY & 4-DIGIT PIN
        elif action == 'add_staff':
            full_name = request.form.get('full_name', '').strip()
            display_name = request.form.get('display_name', '').strip()
            staff_user = request.form.get('staff_username', '').lower().strip()
            staff_pass = request.form.get('staff_password', '').strip()
            staff_pin = request.form.get('staff_pin', '').strip()
            staff_role = request.form.get('staff_role', 'Barista / Kitchen Crew')

            if not staff_user or not staff_pass:
                feedback_msg = "Error: Username and Password are required."
                alert_type = "danger"
            elif staff_pin and (not staff_pin.isdigit() or len(staff_pin) != 4):
                feedback_msg = "Error: Quick Terminal PIN must be exactly 4 numeric digits."
                alert_type = "danger"
            else:
                if not staff_pin:
                    staff_pin = "1234"
                if not display_name:
                    display_name = full_name.split()[0] if full_name else staff_user.capitalize()

                conn = sqlite3.connect(client_db_path)
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT COUNT(*) FROM Staff_Accounts")
                    next_id = f"STF{cursor.fetchone()[0] + 1:03d}"
                    
                    cursor.execute(
                        """INSERT INTO Staff_Accounts (Staff_ID, Full_Name, Display_Name, Username, Password, PIN, Role, Active)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'Yes')""",
                        (next_id, full_name, display_name, staff_user, staff_pass, staff_pin, staff_role)
                    )
                    conn.commit()
                    feedback_msg = f"Success: Provisioned crew key for '{display_name}' ({staff_role}) with PIN: {staff_pin}."
                    alert_type = "success"
                except sqlite3.IntegrityError:
                    feedback_msg = f"Error: A team sub-account named '{staff_user}' is already registered."
                    alert_type = "danger"
                conn.close()

        # 3. RESET STAFF PASSWORD & QUICK PIN
        elif action == 'reset_staff_password':
            staff_id = request.form.get('staff_id')
            new_pass = request.form.get('new_password', '').strip()
            new_pin = request.form.get('new_pin', '').strip()
            
            if staff_id and (new_pass or new_pin):
                if new_pin and (not new_pin.isdigit() or len(new_pin) != 4):
                    feedback_msg = "Error: New Quick PIN must be exactly 4 numeric digits."
                    alert_type = "danger"
                else:
                    conn = sqlite3.connect(client_db_path)
                    cursor = conn.cursor()
                    if new_pass and new_pin:
                        cursor.execute("UPDATE Staff_Accounts SET Password = ?, PIN = ? WHERE Staff_ID = ?", (new_pass, new_pin, staff_id))
                    elif new_pass:
                        cursor.execute("UPDATE Staff_Accounts SET Password = ? WHERE Staff_ID = ?", (new_pass, staff_id))
                    elif new_pin:
                        cursor.execute("UPDATE Staff_Accounts SET PIN = ? WHERE Staff_ID = ?", (new_pin, staff_id))
                    conn.commit()
                    conn.close()
                    feedback_msg = "Security Override: Staff access token passkey and PIN updated successfully."
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
                    conn = sqlite3.connect(client_db_path)
                    ensure_staff_table_exists(client_db_path)
                    heal_database_integrity(conn)
                    conn.close()
                    client_db.update_all_product_costs()
                    feedback_msg = "System Restoration Successful: The database file has been successfully hot-swapped."
                    alert_type = "success"
                except Exception as e:
                    feedback_msg = f"Restoration Fault during file overwrite sequencing: {str(e)}"
                    alert_type = "danger"

        # 7. BULK CSV IMPORT (MULTI-ENCODING, TOKEN-SORTED MATCHING & REPORTING)
        elif action == 'bulk_import':
            target_table = request.form.get('import_target')
            uploaded_file = request.files.get('csv_file')
            
            if not uploaded_file or uploaded_file.filename == '':
                feedback_msg = "Error: No CSV file attached for upload."
                alert_type = "danger"
            else:
                try:
                    raw_bytes = uploaded_file.stream.read()
                    decoded_text = None

                    for enc in ['utf-8-sig', 'utf-8', 'cp1252', 'latin-1', 'iso-8859-1']:
                        try:
                            decoded_text = raw_bytes.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                            
                    if decoded_text is None:
                        decoded_text = raw_bytes.decode('utf-8', errors='replace')

                    stream = io.StringIO(decoded_text, newline=None)
                    df = pd.read_csv(stream)
                    conn = sqlite3.connect(client_db_path, timeout=20.0)

                    # ===== SCENARIO A: PRODUCT FINISHED RECIPES IMPORT =====
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

                        prod_pairs = list(zip(products_db['Product_ID'], products_db['Product_Name']))
                        valid_prod_ids, resolve_product = build_entity_resolver(prod_pairs)

                        ing_pairs = list(zip(ingredients_db['Ingredient_ID'], ingredients_db['Ingredient_Name']))
                        valid_ing_ids, resolve_ingredient = build_entity_resolver(ing_pairs)
                        ing_id_to_default_unit = {str(iid).strip(): str(u).strip() for iid, u in zip(ingredients_db['Ingredient_ID'], ingredients_db['Unit']) if pd.notna(u)}

                        recipes_by_product = {}
                        skipped_rows = []

                        for row_idx, row in df.iterrows():
                            raw_pid = str(row[pid_col]).strip() if pid_col and pd.notna(row.get(pid_col)) else ""
                            raw_pname = str(row[pname_col]).strip() if pname_col and pd.notna(row.get(pname_col)) else ""

                            resolved_pid = resolve_product(raw_pid, raw_pname)
                            if not resolved_pid:
                                skipped_rows.append(f"Row {row_idx+2}: Unknown Product '{raw_pname or raw_pid}' (not found in Products catalog)")
                                continue

                            raw_iid = str(row[iid_col]).strip() if iid_col and pd.notna(row.get(iid_col)) else ""
                            raw_iname = str(row[iname_col]).strip() if iname_col and pd.notna(row.get(iname_col)) else ""

                            resolved_iid = resolve_ingredient(raw_iid, raw_iname)
                            if not resolved_iid:
                                skipped_rows.append(f"Row {row_idx+2}: Unknown Ingredient '{raw_iname or raw_iid}' (not found in Ingredients catalog)")
                                continue

                            try:
                                qty_val = float(row[qty_col]) if qty_col and pd.notna(row.get(qty_col)) else 0.0
                            except (ValueError, TypeError):
                                qty_val = 0.0

                            if qty_val <= 0:
                                skipped_rows.append(f"Row {row_idx+2}: Invalid quantity ({qty_val}) for product {resolved_pid}")
                                continue

                            unit_val = str(row[unit_col]).strip() if unit_col and pd.notna(row.get(unit_col)) else ing_id_to_default_unit.get(resolved_iid, 'pcs')

                            if resolved_pid not in recipes_by_product:
                                recipes_by_product[resolved_pid] = []

                            recipes_by_product[resolved_pid].append({
                                'ingredient_id': resolved_iid,
                                'quantity': qty_val,
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

                            feedback_msg = f"Successfully imported recipes for {len(recipes_by_product)} products ({total_lines} component lines)."
                            if skipped_rows:
                                session['skipped_errors'] = skipped_rows
                                feedback_msg += f" Notice: {len(skipped_rows)} recipe line(s) skipped due to unmatched items. See details below."
                                alert_type = "warning"
                            else:
                                alert_type = "success"
                        else:
                            conn.close()
                            if skipped_rows:
                                session['skipped_errors'] = skipped_rows
                                feedback_msg = f"Import Notice: All {len(skipped_rows)} rows were skipped because items were not found in catalogs. See details below."
                            else:
                                feedback_msg = "Error: No valid recipe rows found in CSV spreadsheet."
                            alert_type = "danger"

                    # ===== SCENARIO B: KITCHEN PREP SUB-RECIPES IMPORT =====
                    elif target_table == 'prep_recipes':
                        col_map = {str(col).lower().strip().replace(' ', '_'): col for col in df.columns}
                        
                        prepped_id_col = col_map.get('prepped_id') or col_map.get('prepped_ingredient_id') or col_map.get('prep_id')
                        prepped_name_col = col_map.get('prepped_name') or col_map.get('prepped_item') or col_map.get('prepped_ingredient') or col_map.get('prep_name')
                        raw_id_col = col_map.get('raw_ingredient_id') or col_map.get('raw_id') or col_map.get('ingredient_id') or col_map.get('ing_id')
                        raw_name_col = col_map.get('raw_ingredient_name') or col_map.get('raw_name') or col_map.get('ingredient_name') or col_map.get('raw_item')
                        qty_col = col_map.get('quantity_required') or col_map.get('quantity') or col_map.get('qty') or col_map.get('amount')
                        unit_col = col_map.get('unit') or col_map.get('uom')
                        yield_col = col_map.get('batch_yield') or col_map.get('yield') or col_map.get('output_yield') or col_map.get('batch_output_yield')

                        ingredients_db = pd.read_sql("SELECT Ingredient_ID, Ingredient_Name, Unit FROM Ingredients", conn)
                        ing_pairs = list(zip(ingredients_db['Ingredient_ID'], ingredients_db['Ingredient_Name']))
                        valid_ing_ids, resolve_ingredient = build_entity_resolver(ing_pairs)
                        ing_id_to_default_unit = {str(iid).strip(): str(u).strip() for iid, u in zip(ingredients_db['Ingredient_ID'], ingredients_db['Unit']) if pd.notna(u)}

                        prep_recipes_by_item = {}
                        skipped_rows = []

                        for row_idx, row in df.iterrows():
                            raw_pid = str(row[prepped_id_col]).strip() if prepped_id_col and pd.notna(row.get(prepped_id_col)) else ""
                            raw_pname = str(row[prepped_name_col]).strip() if prepped_name_col and pd.notna(row.get(prepped_name_col)) else ""

                            resolved_pid = resolve_ingredient(raw_pid, raw_pname)
                            if not resolved_pid:
                                skipped_rows.append(f"Row {row_idx+2}: Prepped component '{raw_pname or raw_pid}' not found in Ingredients catalog. Register it under Ingredients first.")
                                continue

                            raw_iid = str(row[raw_id_col]).strip() if raw_id_col and pd.notna(row.get(raw_id_col)) else ""
                            raw_iname = str(row[raw_name_col]).strip() if raw_name_col and pd.notna(row.get(raw_name_col)) else ""

                            resolved_iid = resolve_ingredient(raw_iid, raw_iname)
                            if not resolved_iid:
                                skipped_rows.append(f"Row {row_idx+2}: Raw ingredient '{raw_iname or raw_iid}' not found in Ingredients catalog.")
                                continue

                            try:
                                qty_val = float(row[qty_col]) if qty_col and pd.notna(row.get(qty_col)) else 0.0
                            except (ValueError, TypeError):
                                qty_val = 0.0

                            if qty_val <= 0:
                                skipped_rows.append(f"Row {row_idx+2}: Invalid quantity ({qty_val}) for prepped item {resolved_pid}")
                                continue

                            unit_val = str(row[unit_col]).strip() if unit_col and pd.notna(row.get(unit_col)) else ing_id_to_default_unit.get(resolved_iid, 'g')

                            try:
                                yield_val = float(row[yield_col]) if yield_col and pd.notna(row.get(yield_col)) else 1.0
                                if yield_val <= 0:
                                    yield_val = 1.0
                            except (ValueError, TypeError):
                                yield_val = 1.0

                            if resolved_pid not in prep_recipes_by_item:
                                prep_recipes_by_item[resolved_pid] = {
                                    'yield': yield_val,
                                    'items': []
                                }

                            if yield_val > 1.0:
                                prep_recipes_by_item[resolved_pid]['yield'] = yield_val

                            prep_recipes_by_item[resolved_pid]['items'].append({
                                'raw_ingredient_id': resolved_iid,
                                'quantity': qty_val,
                                'unit': unit_val
                            })

                        if prep_recipes_by_item:
                            existing_prep_recipes = pd.read_sql("SELECT * FROM Prep_Recipes", conn)
                            updated_prep_ids = list(prep_recipes_by_item.keys())

                            if not existing_prep_recipes.empty:
                                existing_prep_recipes = existing_prep_recipes[~existing_prep_recipes['Prepped_Ingredient_ID'].isin(updated_prep_ids)]

                            new_prep_rows = []
                            total_lines = 0
                            for pid, data in prep_recipes_by_item.items():
                                batch_yield = data['yield']
                                for idx, item in enumerate(data['items'], start=1):
                                    new_prep_rows.append({
                                        'Prep_Recipe_ID': f"{pid}-PREP{idx:03d}",
                                        'Prepped_Ingredient_ID': pid,
                                        'Raw_Ingredient_ID': item['raw_ingredient_id'],
                                        'Quantity_Required': item['quantity'],
                                        'Unit': item['unit'],
                                        'Batch_Yield': batch_yield
                                    })
                                    total_lines += 1

                            combined_prep_recipes = pd.concat([existing_prep_recipes, pd.DataFrame(new_prep_rows)], ignore_index=True) if new_prep_rows else existing_prep_recipes
                            combined_prep_recipes.to_sql('Prep_Recipes', conn, if_exists='replace', index=False)
                            
                            heal_database_integrity(conn)
                            conn.commit()
                            conn.close()

                            client_db.update_all_product_costs()
                            client_db.log_user_action(
                                username=username,
                                action_type="BULK_IMPORT_PREP_RECIPES",
                                module="Recipes",
                                details=f"Bulk imported kitchen prep formulas for {len(prep_recipes_by_item)} components ({total_lines} lines)"
                            )

                            feedback_msg = f"Successfully imported kitchen prep blueprints for {len(prep_recipes_by_item)} items ({total_lines} constituent lines)."
                            if skipped_rows:
                                session['skipped_errors'] = skipped_rows
                                feedback_msg += f" Notice: {len(skipped_rows)} kitchen prep line(s) skipped due to unmatched items. See details below."
                                alert_type = "warning"
                            else:
                                alert_type = "success"
                        else:
                            conn.close()
                            if skipped_rows:
                                session['skipped_errors'] = skipped_rows
                                feedback_msg = f"Import Notice: All {len(skipped_rows)} rows were skipped because constituents were not found in Ingredients. See details below."
                            else:
                                feedback_msg = "Error: No valid kitchen prep rows found in CSV spreadsheet."
                            alert_type = "danger"

                    # ===== SCENARIO C: INGREDIENTS OR PRODUCTS SAFE UPSERT =====
                    else:
                        cursor = conn.cursor()
                        is_ingredients = (target_table == 'ingredients')
                        target_table_name = 'Ingredients' if is_ingredients else 'Products'
                        id_col = 'Ingredient_ID' if is_ingredients else 'Product_ID'
                        name_col = 'Ingredient_Name' if is_ingredients else 'Product_Name'
                        prefix = "ING" if is_ingredients else "PROD"
                        
                        cursor.execute(f"PRAGMA table_info({target_table_name})")
                        valid_cols = [row[1] for row in cursor.fetchall()]

                        if is_ingredients:
                            cursor.execute("SELECT Ingredient_ID, Ingredient_Name, Ingredient_Type FROM Ingredients")
                            existing_rows = cursor.fetchall()
                            id_to_type = {r[0]: (r[2] or 'RAW') for r in existing_rows if r and r[0]}
                            occupied_ids = set(id_to_type.keys())
                            ing_pairs = [(r[0], r[1]) for r in existing_rows]
                            valid_ids, resolve_existing = build_entity_resolver(ing_pairs)
                        else:
                            cursor.execute("SELECT Product_ID, Product_Name FROM Products")
                            existing_rows = cursor.fetchall()
                            occupied_ids = set(r[0] for r in existing_rows if r and r[0])
                            prod_pairs = [(r[0], r[1]) for r in existing_rows]
                            valid_ids, resolve_existing = build_entity_resolver(prod_pairs)

                        cursor.execute(f"SELECT {id_col} FROM {target_table_name} WHERE {id_col} LIKE '{prefix}%'")
                        existing_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
                        nums = []
                        for eid in existing_ids:
                            try:
                                nums.append(int(eid.replace(prefix, '')))
                            except ValueError:
                                pass
                        next_seq_num = max(nums) + 1 if nums else 1

                        processed_count = 0

                        for _, row in df.iterrows():
                            row_dict = {k: v for k, v in row.items() if pd.notna(v)}
                            
                            name_val = str(row_dict.get(name_col, '')).strip()
                            if not name_val or name_val.lower() == 'nan': 
                                continue
                            
                            csv_id = str(row_dict.get(id_col, '')).strip()

                            if is_ingredients:
                                try:
                                    p_cost = float(pd.to_numeric(row_dict.get('Purchase_Cost', 0.0), errors='coerce') or 0.0)
                                except (ValueError, TypeError):
                                    p_cost = 0.0
                                    
                                try:
                                    p_size = float(pd.to_numeric(row_dict.get('Pack_Size', 1.0), errors='coerce') or 1.0)
                                    if p_size <= 0: 
                                        p_size = 1.0
                                except (ValueError, TypeError):
                                    p_size = 1.0
                                    
                                try:
                                    c_unit = float(pd.to_numeric(row_dict.get('Cost_Per_Unit', 0.0), errors='coerce') or 0.0)
                                except (ValueError, TypeError):
                                    c_unit = 0.0

                                row_dict['Pack_Size'] = p_size
                                
                                if p_cost > 0:
                                    row_dict['Purchase_Cost'] = p_cost
                                    row_dict['Cost_Per_Unit'] = round(p_cost / p_size, 4)
                                elif c_unit > 0:
                                    row_dict['Cost_Per_Unit'] = c_unit
                                    row_dict['Purchase_Cost'] = round(c_unit * p_size, 2)
                            
                            target_id = resolve_existing(csv_id, name_val)

                            if target_id:
                                if is_ingredients:
                                    is_prepped = (id_to_type.get(target_id) == 'PREPPED')
                                    if is_prepped and 'Ingredient_Type' in row_dict and row_dict['Ingredient_Type'] != 'PREPPED':
                                        del row_dict['Ingredient_Type']

                                update_cols = [k for k in row_dict.keys() if k in valid_cols and k != id_col]
                                if update_cols:
                                    set_clause = ", ".join([f"{k} = ?" for k in update_cols])
                                    update_values = tuple([row_dict[k] for k in update_cols] + [target_id])
                                    cursor.execute(f"UPDATE {target_table_name} SET {set_clause} WHERE {id_col} = ?", update_values)

                            else:
                                if csv_id and csv_id in occupied_ids:
                                    target_id = f"{prefix}{next_seq_num:03d}"
                                    next_seq_num += 1
                                elif csv_id and csv_id.lower() not in ['nan', 'none', 'null', '']:
                                    target_id = csv_id
                                else:
                                    target_id = f"{prefix}{next_seq_num:03d}"
                                    next_seq_num += 1

                                row_dict[id_col] = target_id
                                occupied_ids.add(target_id)

                                if is_ingredients and 'Ingredient_Type' not in row_dict:
                                    row_dict['Ingredient_Type'] = 'RAW'

                                insert_data = {k: v for k, v in row_dict.items() if k in valid_cols}
                                cols = ", ".join(insert_data.keys())
                                placeholders = ", ".join(["?"] * len(insert_data))
                                values = tuple(insert_data.values())
                                cursor.execute(f"INSERT INTO {target_table_name} ({cols}) VALUES ({placeholders})", values)

                            processed_count += 1

                        heal_database_integrity(conn)
                        conn.commit()
                        conn.close()

                        client_db.update_all_product_costs()
                        feedback_msg = f"Success: Safely processed {processed_count} records into {target_table_name}. Packaging costs verified and sub-recipes preserved."
                        alert_type = "success"

                except Exception as e:
                    feedback_msg = f"CSV Format Error: {str(e)}"
                    alert_type = "danger"

        # 8. DOWNLOAD CSV TEMPLATES
        elif action == 'download_template':
            template_type = request.form.get('template_type')
            
            try:
                conn = sqlite3.connect(client_db_path)
                if template_type == 'recipes':
                    df = pd.DataFrame(columns=[
                        'Product_ID', 'Product_Name', 'Ingredient_ID', 'Ingredient_Name', 'Quantity_Required', 'Unit'
                    ])
                elif template_type == 'prep_recipes':
                    df = pd.DataFrame(columns=[
                        'Prepped_ID', 'Prepped_Name', 'Raw_Ingredient_ID', 'Raw_Ingredient_Name', 'Quantity_Required', 'Unit', 'Batch_Yield'
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

        # 9. EXPORT CSV DATA
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

                elif export_target == 'prep_recipes':
                    query = """
                        SELECT 
                            pr.Prepped_Ingredient_ID AS Prepped_ID,
                            COALESCE(i_prep.Ingredient_Name, pr.Prepped_Ingredient_ID) AS Prepped_Name,
                            pr.Raw_Ingredient_ID,
                            COALESCE(i_raw.Ingredient_Name, pr.Raw_Ingredient_ID) AS Raw_Ingredient_Name,
                            pr.Quantity_Required,
                            pr.Unit,
                            pr.Batch_Yield
                        FROM Prep_Recipes pr
                        LEFT JOIN Ingredients i_prep ON pr.Prepped_Ingredient_ID = i_prep.Ingredient_ID
                        LEFT JOIN Ingredients i_raw ON pr.Raw_Ingredient_ID = i_raw.Ingredient_ID
                        ORDER BY pr.Prepped_Ingredient_ID, pr.Raw_Ingredient_ID
                    """
                    df = pd.read_sql(query, conn)
                    conn.close()

                    if not df.empty:
                        df['Quantity_Required'] = pd.to_numeric(df['Quantity_Required'], errors='coerce').fillna(0.0)
                        df['Batch_Yield'] = pd.to_numeric(df['Batch_Yield'], errors='coerce').fillna(1.0)

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
                        tables_to_wipe.extend(['Sales', 'Inventory_Log', 'Inventory_Audit_Log', 'Expenses', 'Cash_Drawer_Logs'])
                        wiped_categories.append("Operational Activity Logs")
                        
                    if request.form.get('wipe_recipes'):
                        tables_to_wipe.extend(['Recipes', 'Prep_Recipes', 'Modifier_Recipes'])
                        wiped_categories.append("Linked Product Recipes & Kitchen Prep Sub-Recipes")
                        
                    if request.form.get('wipe_ingredients'):
                        tables_to_wipe.extend(['Ingredients'])
                        wiped_categories.append("Raw Material Ingredients List")
                        
                    if request.form.get('wipe_products'):
                        tables_to_wipe.extend(['Products', 'Modifiers'])
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

        # 11. SAVE INVENTORY AUDIT & GOVERNANCE POLICY
        elif action == 'save_audit_policy':
            enforce_blind = 'yes' if request.form.get('enforce_blind_count') == 'yes' else 'no'
            try:
                alert_pct = float(request.form.get('variance_alert_pct', 2.0) or 2.0)
                if alert_pct < 0:
                    alert_pct = 0.0
            except (ValueError, TypeError):
                alert_pct = 2.0
                
            try:
                alert_val = float(request.form.get('variance_alert_value', 100.0) or 100.0)
                if alert_val < 0:
                    alert_val = 0.0
            except (ValueError, TypeError):
                alert_val = 100.0

            ensure_store_settings_exist(client_db_path)
            conn = sqlite3.connect(client_db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO Store_Settings (Setting_Key, Setting_Value) VALUES ('enforce_blind_count', ?)", (enforce_blind,))
            cursor.execute("INSERT OR REPLACE INTO Store_Settings (Setting_Key, Setting_Value) VALUES ('variance_alert_pct', ?)", (str(alert_pct),))
            cursor.execute("INSERT OR REPLACE INTO Store_Settings (Setting_Key, Setting_Value) VALUES ('variance_alert_value', ?)", (str(alert_val),))
            conn.commit()
            conn.close()

            if hasattr(client_db, 'log_user_action'):
                try:
                    client_db.log_user_action(
                        username=username,
                        action_type="UPDATE_AUDIT_POLICY",
                        module="Settings",
                        details=f"Updated audit policy: Blind Counting={enforce_blind}, Alert Threshold={alert_pct}%, Loss Trigger=PHP {alert_val:.2f}"
                    )
                except Exception:
                    pass

            feedback_msg = "Success: Inventory Audit & Governance policy updated successfully."
            alert_type = "success"

        return redirect(f"/portal/{username}/settings?msg={feedback_msg}&alert_type={alert_type}")

    # ===== GET METHOD: HEAL INTEGRITY & RETRIEVE NOTICES =====
    conn = sqlite3.connect(client_db_path)
    heal_database_integrity(conn)
    staff_df = pd.read_sql("SELECT * FROM Staff_Accounts", conn)
    conn.close()
    
    staff_list = staff_df.to_dict(orient='records') if not staff_df.empty else []
    skipped_errors = session.pop('skipped_errors', None)
    store_settings = get_store_settings(client_db_path)

    return render_template(
        'settings.html', 
        username=username, 
        msg=request.args.get('msg', feedback_msg),
        alert_type=request.args.get('alert_type', alert_type),
        staff_members=staff_list,
        skipped_errors=skipped_errors,
        store_settings=store_settings
    )