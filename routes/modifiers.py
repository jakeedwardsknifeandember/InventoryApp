# routes/modifiers.py - Relational Modifier Sets, Option Pricing & Portion Costing Controller
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd
import sqlite3

modifiers_bp = Blueprint('modifiers', __name__)

def ensure_modifier_tables(db_path):
    """Ensures Modifier_Groups, Modifiers (with Group_ID & Category migration), Modifier_Recipes, and Product_Modifiers tables exist."""
    conn = sqlite3.connect(db_path, timeout=20.0)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Modifier_Groups (
            Group_ID TEXT PRIMARY KEY,
            Group_Name TEXT NOT NULL,
            Selection_Type TEXT DEFAULT 'multiple',
            Active TEXT DEFAULT 'Yes'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Modifiers (
            Modifier_ID TEXT PRIMARY KEY,
            Group_ID TEXT DEFAULT '',
            Modifier_Name TEXT,
            Category TEXT DEFAULT 'General',
            Price REAL DEFAULT 0.0,
            Active TEXT DEFAULT 'Yes'
        )
    """)

    # Auto-migration: Check if existing Modifiers table is missing Group_ID or Category
    cursor.execute("PRAGMA table_info(Modifiers)")
    cols = [col[1] for col in cursor.fetchall()]
    if 'Group_ID' not in cols:
        cursor.execute("ALTER TABLE Modifiers ADD COLUMN Group_ID TEXT DEFAULT ''")
    if 'Category' not in cols:
        cursor.execute("ALTER TABLE Modifiers ADD COLUMN Category TEXT DEFAULT 'General'")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Modifier_Recipes (
            Modifier_ID TEXT,
            Ingredient_ID TEXT,
            Quantity_Required REAL DEFAULT 0.0,
            Unit TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Product_Modifiers (
            Product_ID TEXT,
            Group_ID TEXT,
            PRIMARY KEY (Product_ID, Group_ID)
        )
    """)

    # Backward compatibility: assign legacy orphaned modifiers into a default "Add-ons & Upgrades" group
    cursor.execute("SELECT COUNT(*) FROM Modifiers WHERE Group_ID IS NULL OR TRIM(Group_ID) = ''")
    orphaned_cnt = cursor.fetchone()[0]
    if orphaned_cnt > 0:
        cursor.execute("SELECT Group_ID FROM Modifier_Groups WHERE Group_Name = 'Add-ons & Upgrades'")
        existing_grp = cursor.fetchone()
        if existing_grp:
            grp_id = existing_grp[0]
        else:
            grp_id = 'MODGRP001'
            cursor.execute("INSERT OR IGNORE INTO Modifier_Groups (Group_ID, Group_Name, Selection_Type, Active) VALUES (?, 'Add-ons & Upgrades', 'multiple', 'Yes')", (grp_id,))

        cursor.execute("UPDATE Modifiers SET Group_ID = ? WHERE Group_ID IS NULL OR TRIM(Group_ID) = ''", (grp_id,))

    conn.commit()
    conn.close()

def normalize_recipe_qty(qty, selected_unit, base_unit):
    """Normalizes recipe input quantity into the ingredient's actual database base unit."""
    try:
        qty = float(qty)
    except (ValueError, TypeError):
        qty = 0.0
        
    s_unit = str(selected_unit).strip().lower()
    b_unit = str(base_unit).strip().lower()

    if b_unit == 'g':
        return (qty * 1000.0, 'g') if s_unit == 'kg' else (qty, 'g')
    elif b_unit in ['ml', 'l']:
        if b_unit == 'ml':
            return (qty * 1000.0, 'ml') if s_unit == 'l' else (qty, 'ml')
        elif b_unit == 'l':
            return (qty / 1000.0, 'L') if s_unit == 'ml' else (qty, 'L')
    elif b_unit == 'kg':
        return (qty / 1000.0, 'kg') if s_unit == 'g' else (qty, 'kg')
    return (qty, selected_unit)

@modifiers_bp.route('/portal/<username>/modifiers', methods=['GET', 'POST'])
def web_modifiers_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    if not session.get('staff_role') and session.get('logged_in_user') == username:
        session['staff_role'] = 'Platform Owner Admin'

    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Modifiers management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    client_db_path = f"data/client_{username}.db"
    ensure_modifier_tables(client_db_path)
    db = InventoryDB(client_db_path)
    
    if request.method == 'POST':
        action = request.form.get('action_type')

        # 1. ACTION: ADD NEW MODIFIER SET (GROUP) WITH NESTED OPTIONS
        if action == 'add_modifier_group':
            group_name = request.form.get('group_name', '').strip()
            selection_type = request.form.get('selection_type', 'multiple').strip()
            option_names = request.form.getlist('option_name[]')
            option_prices = request.form.getlist('option_price[]')

            if not group_name:
                flash("Error: Modifier set name cannot be empty.", "danger")
            else:
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()

                cursor.execute("SELECT Group_ID FROM Modifier_Groups WHERE Group_ID LIKE 'MODGRP%'")
                existing_grp_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
                nums = []
                for gid in existing_grp_ids:
                    try:
                        nums.append(int(gid.replace('MODGRP', '')))
                    except ValueError:
                        pass
                next_grp_num = max(nums) + 1 if nums else 1
                new_grp_id = f"MODGRP{next_grp_num:03d}"

                cursor.execute("""
                    INSERT INTO Modifier_Groups (Group_ID, Group_Name, Selection_Type, Active)
                    VALUES (?, ?, ?, 'Yes')
                """, (new_grp_id, group_name, selection_type))

                cursor.execute("SELECT Modifier_ID FROM Modifiers WHERE Modifier_ID LIKE 'MOD%'")
                existing_mod_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
                mod_nums = []
                for mid in existing_mod_ids:
                    try:
                        mod_nums.append(int(mid.replace('MOD', '')))
                    except ValueError:
                        pass
                next_mod_num = max(mod_nums) + 1 if mod_nums else 1

                for opt_name, opt_price in zip(option_names, option_prices):
                    opt_name_clean = opt_name.strip()
                    if opt_name_clean:
                        try:
                            price_val = float(opt_price or 0.0)
                        except (ValueError, TypeError):
                            price_val = 0.0

                        mod_id = f"MOD{next_mod_num:03d}"
                        next_mod_num += 1

                        cursor.execute("""
                            INSERT INTO Modifiers (Modifier_ID, Group_ID, Modifier_Name, Category, Price, Active)
                            VALUES (?, ?, ?, ?, ?, 'Yes')
                        """, (mod_id, new_grp_id, opt_name_clean, group_name, price_val))

                conn.commit()
                conn.close()
                flash(f"Modifier set '{group_name}' created successfully.", "success")

        # 2. ACTION: EDIT EXISTING MODIFIER SET
        elif action == 'edit_modifier_group':
            group_id = request.form.get('group_id', '').strip()
            group_name = request.form.get('group_name', '').strip()
            selection_type = request.form.get('selection_type', 'multiple').strip()

            existing_opt_ids = request.form.getlist('existing_option_id[]')
            existing_opt_names = request.form.getlist('existing_option_name[]')
            existing_opt_prices = request.form.getlist('existing_option_price[]')

            new_opt_names = request.form.getlist('new_option_name[]')
            new_opt_prices = request.form.getlist('new_option_price[]')

            if group_id and group_name:
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE Modifier_Groups
                    SET Group_Name = ?, Selection_Type = ?
                    WHERE Group_ID = ?
                """, (group_name, selection_type, group_id))

                for oid, oname, oprice in zip(existing_opt_ids, existing_opt_names, existing_opt_prices):
                    if oid and oname.strip():
                        try:
                            pval = float(oprice or 0.0)
                        except (ValueError, TypeError):
                            pval = 0.0
                        cursor.execute("""
                            UPDATE Modifiers
                            SET Modifier_Name = ?, Price = ?, Category = ?
                            WHERE Modifier_ID = ?
                        """, (oname.strip(), pval, group_name, oid))

                cursor.execute("SELECT Modifier_ID FROM Modifiers WHERE Modifier_ID LIKE 'MOD%'")
                existing_mod_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
                mod_nums = []
                for mid in existing_mod_ids:
                    try:
                        mod_nums.append(int(mid.replace('MOD', '')))
                    except ValueError:
                        pass
                next_mod_num = max(mod_nums) + 1 if mod_nums else 1

                for nname, nprice in zip(new_opt_names, new_opt_prices):
                    if nname.strip():
                        try:
                            pval = float(nprice or 0.0)
                        except (ValueError, TypeError):
                            pval = 0.0
                        mod_id = f"MOD{next_mod_num:03d}"
                        next_mod_num += 1

                        cursor.execute("""
                            INSERT INTO Modifiers (Modifier_ID, Group_ID, Modifier_Name, Category, Price, Active)
                            VALUES (?, ?, ?, ?, ?, 'Yes')
                        """, (mod_id, group_id, nname.strip(), group_name, pval))

                conn.commit()
                conn.close()
                flash(f"Modifier set '{group_name}' updated successfully.", "success")

        # 3. ACTION: DELETE MODIFIER SET
        elif action == 'delete_modifier_group':
            group_id = request.form.get('group_id', '').strip()
            if group_id:
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()

                cursor.execute("SELECT Modifier_ID FROM Modifiers WHERE Group_ID = ?", (group_id,))
                child_mods = [r[0] for r in cursor.fetchall() if r and r[0]]

                for cmid in child_mods:
                    cursor.execute("DELETE FROM Modifier_Recipes WHERE Modifier_ID = ?", (cmid,))
                
                cursor.execute("DELETE FROM Modifiers WHERE Group_ID = ?", (group_id,))
                cursor.execute("DELETE FROM Modifier_Groups WHERE Group_ID = ?", (group_id,))
                cursor.execute("DELETE FROM Product_Modifiers WHERE Group_ID = ?", (group_id,))

                conn.commit()
                conn.close()
                flash("Modifier set and linked option references removed cleanly.", "warning")

        # 4. ACTION: DELETE SINGLE MODIFIER OPTION
        elif action == 'delete_single_modifier':
            mod_id = request.form.get('modifier_id', '').strip()
            if mod_id:
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM Modifiers WHERE Modifier_ID = ?", (mod_id,))
                cursor.execute("DELETE FROM Modifier_Recipes WHERE Modifier_ID = ?", (mod_id,))
                conn.commit()
                conn.close()
                flash("Option removed from modifier set.", "info")

        # 5. ACTION: SAVE RECIPE FORMULA FOR SPECIFIC MODIFIER OPTION
        elif action == 'save_modifier_recipe':
            mod_id = request.form.get('modifier_id', '').strip()
            ing_ids = request.form.getlist('ingredient_id[]')
            qtys = request.form.getlist('quantity[]')
            units = request.form.getlist('unit[]')

            ingredients_df = db.read_tab('Ingredients')
            base_unit_map = {}
            if not ingredients_df.empty:
                base_unit_map = dict(zip(ingredients_df['Ingredient_ID'].astype(str), ingredients_df['Unit'].astype(str)))

            recipe_items = []
            for i, q, u in zip(ing_ids, qtys, units):
                if i and q:
                    b_unit = base_unit_map.get(str(i), u)
                    norm_qty, norm_unit = normalize_recipe_qty(q, u, b_unit)
                    recipe_items.append({
                        'ingredient_id': str(i).strip(),
                        'quantity': norm_qty,
                        'unit': norm_unit
                    })

            conn = sqlite3.connect(client_db_path, timeout=20.0)
            cursor = conn.cursor()
            
            # Inspect existing columns in Modifier_Recipes to prevent OperationalError on legacy tables
            cursor.execute("PRAGMA table_info(Modifier_Recipes)")
            mr_cols = [col[1] for col in cursor.fetchall()]

            cursor.execute("DELETE FROM Modifier_Recipes WHERE Modifier_ID = ?", (mod_id,))
            for idx, item in enumerate(recipe_items, 1):
                if 'Modifier_Recipe_ID' in mr_cols:
                    cursor.execute("""
                        INSERT INTO Modifier_Recipes (Modifier_Recipe_ID, Modifier_ID, Ingredient_ID, Quantity_Required, Unit)
                        VALUES (?, ?, ?, ?, ?)
                    """, (f"{mod_id}-MR{idx:03d}", mod_id, item['ingredient_id'], item['quantity'], item['unit']))
                else:
                    cursor.execute("""
                        INSERT INTO Modifier_Recipes (Modifier_ID, Ingredient_ID, Quantity_Required, Unit)
                        VALUES (?, ?, ?, ?)
                    """, (mod_id, item['ingredient_id'], item['quantity'], item['unit']))
            
            conn.commit()
            conn.close()

            flash("Raw ingredient depletion formula updated.", "success")

        return redirect(f"/portal/{username}/modifiers")

    # READ ALL MODIFIER GROUPS WITH NESTED OPTIONS AND COSTS
    modifier_groups_list = []
    dropdown_ingredients = []

    ingredients_df = db.read_tab('Ingredients')
    if ingredients_df is not None and not ingredients_df.empty:
        dropdown_ingredients = ingredients_df.to_dict('records')

    conn = sqlite3.connect(client_db_path, timeout=20.0)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Group_ID, Group_Name, Selection_Type 
        FROM Modifier_Groups 
        WHERE (Active = 'Yes' OR Active = 'YES')
        ORDER BY Group_Name ASC
    """)
    raw_groups = cursor.fetchall()

    for gid, gname, stype in raw_groups:
        cursor.execute("""
            SELECT Modifier_ID, Modifier_Name, Price 
            FROM Modifiers 
            WHERE Group_ID = ? AND (Active = 'Yes' OR Active = 'YES')
            ORDER BY Price ASC, Modifier_Name ASC
        """, (gid,))
        raw_options = cursor.fetchall()

        options_data = []
        for mid, mname, price in raw_options:
            cursor.execute("""
                SELECT mr.Ingredient_ID, COALESCE(i.Ingredient_Name, mr.Ingredient_ID),
                       mr.Quantity_Required, mr.Unit, COALESCE(i.Cost_Per_Unit, 0.0)
                FROM Modifier_Recipes mr
                LEFT JOIN Ingredients i ON mr.Ingredient_ID = i.Ingredient_ID
                WHERE mr.Modifier_ID = ?
            """, (mid,))
            recipe_rows = cursor.fetchall()

            items = []
            total_cost = 0.0
            for r in recipe_rows:
                qty = float(r[2] or 0.0)
                cost = float(r[4] or 0.0)
                line_cost = qty * cost
                total_cost += line_cost
                items.append({
                    'Ingredient_ID': str(r[0]),
                    'Ingredient_Name': str(r[1]),
                    'Quantity': qty,
                    'Unit': str(r[3] or ''),
                    'Cost': line_cost
                })

            price_f = float(price or 0.0)
            profit = price_f - total_cost
            margin = (profit / price_f * 100.0) if price_f > 0 else 0.0

            options_data.append({
                'Modifier_ID': mid,
                'Modifier_Name': mname,
                'Price': price_f,
                'Cost': total_cost,
                'Profit': profit,
                'Margin': margin,
                'Items': items
            })

        modifier_groups_list.append({
            'Group_ID': gid,
            'Group_Name': gname,
            'Selection_Type': stype or 'multiple',
            'Options': options_data
        })

    conn.close()

    return render_template(
        'modifiers.html',
        username=username,
        modifier_groups=modifier_groups_list,
        ingredients=dropdown_ingredients
    )