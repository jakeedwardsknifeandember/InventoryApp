# routes/modifiers.py - Enterprise Modifier Recipe & Portion Costing Controller
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd
import sqlite3

modifiers_bp = Blueprint('modifiers', __name__)

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

    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Modifiers management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    db_path = f"data/client_{username}.db"
    db = InventoryDB(db_path)
    
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        if action == 'add_modifier':
            mod_name = request.form.get('modifier_name', '').strip()
            try:
                price = float(request.form.get('price', 0.0) or 0.0)
            except (ValueError, TypeError):
                price = 0.0
            
            mods_df = db.read_tab('Modifiers')
            mod_id = f"MOD{len(mods_df) + 1:03d}"
            
            new_row_df = pd.DataFrame([{'Modifier_ID': mod_id, 'Modifier_Name': mod_name, 'Price': price, 'Active': 'Yes'}])
            if not mods_df.empty:
                mods_df = pd.concat([mods_df, new_row_df], ignore_index=True)
            else:
                mods_df = new_row_df
                
            db.save_tab('Modifiers', mods_df)
            db.log_user_action(username, "ADD_MODIFIER", "Modifiers", f"Created modifier '{mod_name}' (PHP {price:.2f})")
            flash(f"Modifier '{mod_name}' added successfully.", 'success')

        elif action == 'save_modifier_recipe':
            mod_id = request.form.get('modifier_id')
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
            
            # Resilient direct commit to Modifier_Recipes table
            conn = sqlite3.connect(db_path, timeout=20.0)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Modifier_Recipes (
                    Modifier_ID TEXT,
                    Ingredient_ID TEXT,
                    Quantity_Required REAL,
                    Unit TEXT
                )
            """)
            cursor.execute("DELETE FROM Modifier_Recipes WHERE Modifier_ID = ?", (mod_id,))
            for item in recipe_items:
                cursor.execute("""
                    INSERT INTO Modifier_Recipes (Modifier_ID, Ingredient_ID, Quantity_Required, Unit)
                    VALUES (?, ?, ?, ?)
                """, (mod_id, item['ingredient_id'], item['quantity'], item['unit']))
            conn.commit()
            conn.close()

            if hasattr(db, 'save_modifier_recipe'):
                try:
                    db.save_modifier_recipe(mod_id, recipe_items, username=username)
                except Exception:
                    pass

            flash("Modifier ingredient recipe updated successfully.", 'success')

        elif action == 'delete_modifier':
            mod_id = request.form.get('modifier_id')
            mods_df = db.read_tab('Modifiers')
            if not mods_df.empty:
                mods_df = mods_df[mods_df['Modifier_ID'] != mod_id]
                db.save_tab('Modifiers', mods_df)
            
            conn = sqlite3.connect(db_path, timeout=20.0)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifier_Recipes'")
            if cursor.fetchone():
                cursor.execute("DELETE FROM Modifier_Recipes WHERE Modifier_ID = ?", (mod_id,))
                conn.commit()
            conn.close()

            flash("Modifier deleted successfully.", 'info')

        return redirect(f"/portal/{username}/modifiers")

    # READ MODIFIERS
    mods_df = db.read_tab('Modifiers')
    
    # DUAL-LAYER FAILSAFE INGREDIENTS FETCHING
    dropdown_ingredients = []
    ingredients_df = db.read_tab('Ingredients')
    
    if ingredients_df is not None and not ingredients_df.empty:
        dropdown_ingredients = ingredients_df.to_dict('records')
    else:
        try:
            conn = sqlite3.connect(db_path, timeout=20.0)
            cursor = conn.cursor()
            cursor.execute("SELECT Ingredient_ID, Ingredient_Name, Unit FROM Ingredients;")
            rows = cursor.fetchall()
            conn.close()
            for r in rows:
                dropdown_ingredients.append({
                    'Ingredient_ID': str(r[0]),
                    'Ingredient_Name': str(r[1]),
                    'Unit': str(r[2] or 'pcs')
                })
        except Exception:
            dropdown_ingredients = []

    modifiers_list = []

    if not mods_df.empty:
        conn = sqlite3.connect(db_path, timeout=20.0)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Modifier_Recipes (
                Modifier_ID TEXT,
                Ingredient_ID TEXT,
                Quantity_Required REAL,
                Unit TEXT
            )
        """)

        for _, m in mods_df.iterrows():
            m_id = str(m['Modifier_ID'])
            
            cursor.execute("""
                SELECT mr.Ingredient_ID, COALESCE(i.Ingredient_Name, mr.Ingredient_ID), 
                       mr.Quantity_Required, mr.Unit, COALESCE(i.Cost_Per_Unit, 0.0)
                FROM Modifier_Recipes mr
                LEFT JOIN Ingredients i ON mr.Ingredient_ID = i.Ingredient_ID
                WHERE mr.Modifier_ID = ?
            """, (m_id,))
            recipe_rows = cursor.fetchall()

            items = []
            total_cost = 0.0
            
            for r in recipe_rows:
                qty = float(r[2] or 0.0)
                cost = float(r[4] or 0.0)
                unit = str(r[3] or '')
                
                line_cost = qty * cost
                total_cost += line_cost

                items.append({
                    'Ingredient_ID': str(r[0]),
                    'Ingredient_Name': str(r[1]),
                    'Quantity': qty,
                    'Unit': unit,
                    'Cost': line_cost
                })

            price = float(pd.to_numeric(m.get('Price', 0.0), errors='coerce') or 0.0)
            profit = price - total_cost

            modifiers_list.append({
                'Modifier_ID': m_id,
                'Modifier_Name': m.get('Modifier_Name'),
                'Price': price,
                'Cost': total_cost,
                'Profit': profit,
                'Items': items
            })

        conn.close()

    return render_template(
        'modifiers.html',
        username=username,
        modifiers=modifiers_list,
        ingredients=dropdown_ingredients
    )