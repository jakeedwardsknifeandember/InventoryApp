# routes/ingredients.py - Enterprise Raw Materials & Prepped Sub-Assembly Controller
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd
import sqlite3
from collections import defaultdict

ingredients_bp = Blueprint('ingredients', __name__)

def heal_duplicate_ingredients(client_db_path):
    """
    Automatically detects and merges case-insensitive duplicate ingredients
    (e.g., 'CONDENSED MILK' and 'Condensed Milk', 'BROWN SUGAR' and 'Brown Sugar'):
    1. Sums their combined physical inventory stock into one master record.
    2. Re-points all Recipes, Modifier_Recipes, and Prep_Recipes to the master ID.
    3. Purges the duplicate record, breaking UI validation deadlocks.
    """
    try:
        conn = sqlite3.connect(client_db_path, timeout=20.0)
        cursor = conn.cursor()
        cursor.execute("SELECT Ingredient_ID, Ingredient_Name, Current_Stock, Cost_Per_Unit, Purchase_Cost, Pack_Size FROM Ingredients")
        rows = cursor.fetchall()
        
        grouped = defaultdict(list)
        for r in rows:
            norm_name = str(r[1]).strip().lower()
            grouped[norm_name].append({
                'id': str(r[0]),
                'name': str(r[1]),
                'stock': float(r[2] or 0.0),
                'cost': float(r[3] or 0.0),
                'p_cost': float(r[4] or 0.0),
                'pack_size': float(r[5] or 1.0)
            })
            
        for name, items in grouped.items():
            if len(items) > 1:
                # Prefer standard Title Case over ALL CAPS as primary master record
                primary = items[0]
                for it in items:
                    if it['name'] != it['name'].upper() and it['name'][0].isupper():
                        primary = it
                        break
                
                duplicates = [it for it in items if it['id'] != primary['id']]
                combined_stock = sum(it['stock'] for it in items)
                
                best_cost = primary['cost']
                best_pcost = primary['p_cost']
                best_pack = primary['pack_size']
                for it in items:
                    if it['cost'] > 0 and best_cost == 0:
                        best_cost = it['cost']
                        best_pcost = it['p_cost']
                        best_pack = it['pack_size']

                # Update master record with consolidated stock and packaging metrics
                cursor.execute("""
                    UPDATE Ingredients 
                    SET Current_Stock = ?, Cost_Per_Unit = ?, Purchase_Cost = ?, Pack_Size = ?
                    WHERE Ingredient_ID = ?
                """, (combined_stock, best_cost, best_pcost, best_pack, primary['id']))

                for dup in duplicates:
                    dup_id = dup['id']
                    
                    # 1. Repoint Finished Product Recipes
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Recipes'")
                    if cursor.fetchone():
                        cursor.execute("SELECT Product_ID FROM Recipes WHERE Ingredient_ID = ?", (dup_id,))
                        for (pid,) in cursor.fetchall():
                            cursor.execute("SELECT COUNT(*) FROM Recipes WHERE Product_ID = ? AND Ingredient_ID = ?", (pid, primary['id']))
                            if cursor.fetchone()[0] == 0:
                                cursor.execute("UPDATE Recipes SET Ingredient_ID = ? WHERE Product_ID = ? AND Ingredient_ID = ?", (primary['id'], pid, dup_id))
                            else:
                                cursor.execute("DELETE FROM Recipes WHERE Product_ID = ? AND Ingredient_ID = ?", (pid, dup_id))

                    # 2. Repoint Modifier Add-on Recipes
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifier_Recipes'")
                    if cursor.fetchone():
                        cursor.execute("SELECT Modifier_ID FROM Modifier_Recipes WHERE Ingredient_ID = ?", (dup_id,))
                        for (mid,) in cursor.fetchall():
                            cursor.execute("SELECT COUNT(*) FROM Modifier_Recipes WHERE Modifier_ID = ? AND Ingredient_ID = ?", (mid, primary['id']))
                            if cursor.fetchone()[0] == 0:
                                cursor.execute("UPDATE Modifier_Recipes SET Ingredient_ID = ? WHERE Modifier_ID = ? AND Ingredient_ID = ?", (primary['id'], mid, dup_id))
                            else:
                                cursor.execute("DELETE FROM Modifier_Recipes WHERE Modifier_ID = ? AND Ingredient_ID = ?", (mid, dup_id))

                    # 3. Repoint Kitchen Prep Blueprints
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Prep_Recipes'")
                    if cursor.fetchone():
                        cursor.execute("UPDATE Prep_Recipes SET Raw_Ingredient_ID = ? WHERE Raw_Ingredient_ID = ?", (primary['id'], dup_id))
                        cursor.execute("UPDATE Prep_Recipes SET Prepped_Ingredient_ID = ? WHERE Prepped_Ingredient_ID = ?", (primary['id'], dup_id))

                    # 4. Remove redundant duplicate shell
                    cursor.execute("DELETE FROM Ingredients WHERE Ingredient_ID = ?", (dup_id,))
                    
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Duplicate healing warning: {e}")

@ingredients_bp.route('/portal/<username>/ingredients', methods=['GET', 'POST'])
def web_ingredients_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Ingredients management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    client_db_path = f"data/client_{username}.db"
    heal_duplicate_ingredients(client_db_path)
    db = InventoryDB(client_db_path)

    if request.method == 'POST':
        action = request.form.get('action_type')
        ingredient_id = request.form.get('ingredient_id')
        
        # 1. ACTION: REGISTER NEW INGREDIENT WITH TWO-TIER PACK CONVERSION
        if action == 'add_ingredient':
            base_unit = request.form.get('unit', 'g').strip()
            purchase_unit = request.form.get('purchase_unit', 'pack').strip()
            
            try:
                pack_size = float(request.form.get('pack_size', 1.0) or 1.0)
                if pack_size <= 0: pack_size = 1.0
            except ValueError:
                pack_size = 1.0
                
            try:
                purchase_cost = float(request.form.get('purchase_cost', 0.0) or 0.0)
            except ValueError:
                purchase_cost = 0.0
                
            try:
                cost_per_base = float(request.form.get('cost', 0.0) or 0.0)
            except ValueError:
                cost_per_base = 0.0
                
            if purchase_cost > 0 and (cost_per_base == 0 or request.form.get('auto_calc') == 'yes'):
                cost_per_base = purchase_cost / pack_size
            elif cost_per_base > 0 and purchase_cost == 0:
                purchase_cost = cost_per_base * pack_size

            db.add_ingredient({
                'Ingredient_ID': db.generate_ingredient_id(),
                'Ingredient_Name': request.form.get('name'),
                'Category': request.form.get('category', 'General'),
                'Unit': base_unit,
                'Purchase_Unit': purchase_unit,
                'Pack_Size': pack_size,
                'Purchase_Cost': purchase_cost,
                'Current_Stock': float(request.form.get('stock', 0) or 0),
                'Min_Stock': float(request.form.get('min_stock', 0) or 0),
                'Cost_Per_Unit': cost_per_base,
                'Active': 'Yes',
                'Ingredient_Type': request.form.get('ingredient_type', 'RAW')
            })
            
        # 2. ACTION: QUICK STOCK INTAKE
        elif action == 'add_stock':
            additional = float(request.form.get('quantity', 0) or 0)
            df = db.read_tab('Ingredients')
            if not df.empty and ingredient_id:
                row = df[df['Ingredient_ID'] == ingredient_id]
                if not row.empty:
                    current = float(row.iloc[0].get('Current_Stock', 0) or 0)
                    db.update_ingredient(ingredient_id, {'Current_Stock': current + additional})
                    
        # 3. ACTION: MODIFY EXISTING INGREDIENT CONVERSION METRICS
        elif action == 'edit_ingredient':
            if ingredient_id:
                base_unit = request.form.get('unit', 'g').strip()
                purchase_unit = request.form.get('purchase_unit', 'pack').strip()
                
                try:
                    pack_size = float(request.form.get('pack_size', 1.0) or 1.0)
                    if pack_size <= 0: pack_size = 1.0
                except ValueError:
                    pack_size = 1.0
                    
                try:
                    purchase_cost = float(request.form.get('purchase_cost', 0.0) or 0.0)
                except ValueError:
                    purchase_cost = 0.0
                    
                try:
                    cost_per_base = float(request.form.get('cost', 0.0) or 0.0)
                except ValueError:
                    cost_per_base = 0.0

                if purchase_cost > 0:
                    cost_per_base = purchase_cost / pack_size
                elif cost_per_base > 0 and purchase_cost == 0:
                    purchase_cost = cost_per_base * pack_size

                db.update_ingredient(ingredient_id, {
                    'Ingredient_Name': request.form.get('name'),
                    'Category': request.form.get('category', 'General'),
                    'Unit': base_unit,
                    'Purchase_Unit': purchase_unit,
                    'Pack_Size': pack_size,
                    'Purchase_Cost': purchase_cost,
                    'Min_Stock': float(request.form.get('min_stock', 0) or 0),
                    'Cost_Per_Unit': cost_per_base,
                    'Ingredient_Type': request.form.get('ingredient_type', 'RAW')
                })
                
        # 4. ACTION: ARCHIVE OR DELETE INGREDIENT
        elif action == 'delete_ingredient':
            if ingredient_id:
                success, msg = db.delete_ingredient(ingredient_id)
                if not success:
                    return redirect(f"/portal/{username}/ingredients?error={msg}")
        
        db.update_all_product_costs()
        heal_duplicate_ingredients(client_db_path)
        return redirect(f"/portal/{username}/ingredients?type=" + request.form.get('ingredient_type', 'RAW'))

    # ===== GET DATA =====
    heal_duplicate_ingredients(client_db_path)
    df = db.get_inventory_status()
    
    categories = []
    ingredients_list = []

    current_type = request.args.get('type', 'RAW').upper().strip()
    if current_type not in ['RAW', 'PREPPED']:
        current_type = 'RAW'

    if not df.empty:
        df['Min_Stock'] = pd.to_numeric(df['Min_Stock'], errors='coerce').fillna(0.0)
        df['Cost_Per_Unit'] = pd.to_numeric(df['Cost_Per_Unit'], errors='coerce').fillna(0.0)
        df['Current_Stock'] = pd.to_numeric(df['Current_Stock'], errors='coerce').fillna(0.0)
        df['Pack_Size'] = pd.to_numeric(df['Pack_Size'], errors='coerce').fillna(1.0)
        df['Purchase_Cost'] = pd.to_numeric(df['Purchase_Cost'], errors='coerce').fillna(0.0)
        
        if 'Ingredient_Type' not in df.columns:
            df['Ingredient_Type'] = 'RAW'
        if 'Purchase_Unit' not in df.columns:
            df['Purchase_Unit'] = df['Unit']
            
        if 'Category' in df.columns:
            categories = sorted([c for c in df['Category'].dropna().unique() if str(c).strip()])

        df = df[df['Ingredient_Type'] == current_type]

        if 'Ingredient_Name' in df.columns:
            df = df.sort_values('Ingredient_Name', ascending=True)

        ingredients_list = df.to_dict('records')

    return render_template(
        'ingredients.html', 
        username=username, 
        ingredients=ingredients_list, 
        categories=categories,
        current_type=current_type,
        error_msg=request.args.get('error', '')
    )