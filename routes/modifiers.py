from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd
import sqlite3

modifiers_bp = Blueprint('modifiers', __name__)

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
            price = float(request.form.get('price', 0.0))
            
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
            
            recipe_items = []
            for i, q, u in zip(ing_ids, qtys, units):
                if i and q:
                    val = float(q)
                    if u in ['g', 'ml']:
                        val = val / 1000.0
                    recipe_items.append({
                        'ingredient_id': i,
                        'quantity': val,
                        'unit': u
                    })
            
            db.save_modifier_recipe(mod_id, recipe_items, username=username)
            flash("Modifier ingredient recipe updated successfully.", 'success')

        elif action == 'delete_modifier':
            mod_id = request.form.get('modifier_id')
            mods_df = db.read_tab('Modifiers')
            mods_df = mods_df[mods_df['Modifier_ID'] != mod_id]
            db.save_tab('Modifiers', mods_df)
            
            mod_recipes_df = db.read_tab('Modifier_Recipes')
            if not mod_recipes_df.empty:
                mod_recipes_df = mod_recipes_df[mod_recipes_df['Modifier_ID'] != mod_id]
                db.save_tab('Modifier_Recipes', mod_recipes_df)

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
        for _, m in mods_df.iterrows():
            m_id = m['Modifier_ID']
            recipe_df = db.get_modifier_recipes(m_id)
            items = []
            total_cost = 0.0
            
            if not recipe_df.empty:
                for _, r in recipe_df.iterrows():
                    qty = float(r.get('Quantity_Required', 0))
                    cost = float(r.get('Cost_Per_Unit', 0))
                    unit = r.get('Unit', '')
                    
                    line_cost = qty * cost
                    total_cost += line_cost
                    
                    display_qty = qty
                    if unit in ['g', 'ml']:
                        display_qty = qty * 1000.0
                        
                    items.append({
                        'Ingredient_ID': r.get('Ingredient_ID'),
                        'Ingredient_Name': r.get('Ingredient_Name'),
                        'Quantity': display_qty,
                        'Unit': unit,
                        'Cost': line_cost
                    })

            price = float(m.get('Price', 0))
            profit = price - total_cost

            modifiers_list.append({
                'Modifier_ID': m_id,
                'Modifier_Name': m.get('Modifier_Name'),
                'Price': price,
                'Cost': total_cost,
                'Profit': profit,
                'Items': items
            })

    return render_template(
        'modifiers.html',
        username=username,
        modifiers=modifiers_list,
        ingredients=dropdown_ingredients
    )