# routes/recipes.py - Advanced Recipes Studio Router Blueprint with Active Item State Retention
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import sqlite3
import pandas as pd
import numpy as np
import re
from collections import defaultdict

recipes_bp = Blueprint('recipes', __name__)

def resolve_parent_and_variant(p):
    """
    Intelligently extracts the master parent drink family and variant label.
    Supports explicit database fields as well as standard beverage naming patterns.
    """
    raw_parent = p.get('Parent_Item')
    raw_variant = p.get('Variant_Name')
    
    if raw_parent and str(raw_parent).strip().lower() not in ['nan', 'none', '', 'null']:
        parent = str(raw_parent).strip()
        variant = str(raw_variant).strip() if (raw_variant and str(raw_variant).strip().lower() not in ['nan', 'none', '', 'null']) else 'Regular'
        return parent, variant

    full_name = str(p.get('Product_Name') or '').strip()
    
    prefix_match = re.match(r"^(Hot|Iced|Cold|Warm)\s*[-–—:]?\s*(.+)$", full_name, re.IGNORECASE)
    if prefix_match:
        variant = prefix_match.group(1).strip().capitalize()
        parent = prefix_match.group(2).strip()
        return parent, variant

    suffix_match = re.match(r"^(.+?)\s*[-–—:(]\s*(Hot|Iced|Cold|Warm|12oz|16oz|22oz|Regular|Large)\)?$", full_name, re.IGNORECASE)
    if suffix_match:
        parent = suffix_match.group(1).strip()
        variant = suffix_match.group(2).strip().capitalize()
        return parent, variant

    delimiter_match = re.match(r"^([^-–—(]+)\s*[-–—]\s*(.+)$", full_name)
    if delimiter_match:
        part1 = delimiter_match.group(1).strip()
        part2 = delimiter_match.group(2).strip()
        if part1.lower() in ['hot', 'iced', 'cold', 'warm']:
            return part2, part1.capitalize()
        return part1, part2

    return full_name, "Regular"

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

@recipes_bp.route('/portal/<username>/recipes', methods=['GET', 'POST'])
def web_recipes_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Recipes management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    client_db_path = f"data/client_{username}.db"
    db = InventoryDB(client_db_path)
    
    current_tab = request.args.get('tab', 'product').lower().strip()
    if current_tab not in ['product', 'prep']:
        current_tab = 'product'

    recipe_data = []
    grouped_recipes = {}
    categories = []
    dropdown_ingredients = []
    all_products_list = []

    # ==========================================
    # 1. POST METHOD: COMMIT CONFIGURATIONS
    # ==========================================
    if request.method == 'POST':
        action = request.form.get('action_type')
        recipe_type = request.form.get('recipe_type', 'product').lower().strip()
        target_id = request.form.get('product_id', '').strip()
        
        # SAVE / UPDATE FORMULA (REDIRECTS WITH ACTIVE PRODUCT_ID)
        if action == 'save_recipe':
            ing_ids = request.form.getlist('ingredient_id[]')
            qtys = request.form.getlist('quantity[]')
            units = request.form.getlist('unit[]')
            
            try:
                batch_yield_val = float(request.form.get('batch_yield', 1.0) or 1.0)
                if batch_yield_val <= 0:
                    batch_yield_val = 1.0
            except ValueError:
                batch_yield_val = 1.0
            
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
                        'ingredient_id': i,
                        'quantity': norm_qty,
                        'unit': norm_unit
                    })
            
            if recipe_type == 'product':
                db.save_recipe(target_id, recipe_items)
            elif recipe_type == 'prep':
                prep_df = db.read_tab('Prep_Recipes')
                if not prep_df.empty:
                    prep_df = prep_df[prep_df['Prepped_Ingredient_ID'] != target_id]
                
                new_records = []
                for idx, item in enumerate(recipe_items):
                    new_records.append({
                        'Prep_Recipe_ID': f"{target_id}-PREP{idx+1:03d}",
                        'Prepped_Ingredient_ID': target_id,
                        'Raw_Ingredient_ID': item['ingredient_id'],
                        'Quantity_Required': item['quantity'],
                        'Unit': item['unit'],
                        'Batch_Yield': batch_yield_val
                    })
                
                if new_records:
                    prep_df = pd.concat([prep_df, pd.DataFrame(new_records)], ignore_index=True)
                db.save_tab('Prep_Recipes', prep_df)
                
            db.update_all_product_costs()
            # Retain active product_id in redirect parameters
            return redirect(f"/portal/{username}/recipes?tab={recipe_type}&product_id={target_id}&msg=Formula specifications successfully saved.")
            
        # DELETE SPECIFICATION OR INGREDIENT SHELL
        elif action == 'delete_recipe':
            if recipe_type == 'product':
                db.delete_recipe(target_id)
                msg = f"Product recipe for {target_id} was successfully cleared."
            elif recipe_type == 'prep':
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM Prep_Recipes WHERE Prepped_Ingredient_ID = ?", (target_id,))
                cursor.execute("DELETE FROM Ingredients WHERE Ingredient_ID = ?", (target_id,))
                conn.commit()
                conn.close()
                msg = f"Kitchen prep component {target_id} and its formula blueprint were permanently removed."
                    
            db.update_all_product_costs()
            return redirect(f"/portal/{username}/recipes?tab={recipe_type}&msg={msg}&alert_type=success")

        # PURGE REDUNDANT DUPLICATE PREPPED ITEMS
        elif action == 'clean_duplicate_prep':
            conn = sqlite3.connect(client_db_path, timeout=20.0)
            cursor = conn.cursor()
            cursor.execute("SELECT Ingredient_ID, LOWER(TRIM(Ingredient_Name)) FROM Ingredients WHERE UPPER(Ingredient_Type) = 'PREPPED'")
            rows = cursor.fetchall()
            
            grouped = defaultdict(list)
            for i_id, name in rows:
                grouped[name].append(i_id)
                
            purged_count = 0
            for name, ids in grouped.items():
                if len(ids) > 1:
                    ids_with_recipes = []
                    for i_id in ids:
                        cursor.execute("SELECT COUNT(*) FROM Prep_Recipes WHERE Prepped_Ingredient_ID = ?", (i_id,))
                        if cursor.fetchone()[0] > 0:
                            ids_with_recipes.append(i_id)
                            
                    primary_id = ids_with_recipes[0] if ids_with_recipes else ids[0]
                    duplicates = [i_id for i_id in ids if i_id != primary_id]
                    
                    for d_id in duplicates:
                        cursor.execute("DELETE FROM Prep_Recipes WHERE Prepped_Ingredient_ID = ?", (d_id,))
                        cursor.execute("DELETE FROM Ingredients WHERE Ingredient_ID = ?", (d_id,))
                        purged_count += 1
                        
            conn.commit()
            conn.close()
            db.update_all_product_costs()
            msg = f"Deduplication complete: Purged {purged_count} duplicate prepped component entries."
            return redirect(f"/portal/{username}/recipes?tab=prep&msg={msg}&alert_type=success")
            
        return redirect(f"/portal/{username}/recipes?tab={recipe_type}")

    # ==========================================
    # 2. GET METHOD: COMPUTE & RENDER WORKSPACE
    # ==========================================
    products_df = db.read_tab('Products')
    ingredients_df = db.read_tab('Ingredients')
    prep_recipes_df = db.read_tab('Prep_Recipes')
    
    ing_lookup = {}
    if not ingredients_df.empty:
        for _, ing in ingredients_df.iterrows():
            cost_val = pd.to_numeric(ing.get('Cost_Per_Unit', 0.0), errors='coerce')
            if pd.isna(cost_val) or np.isnan(cost_val):
                cost_val = 0.0
            ing_lookup[str(ing['Ingredient_ID'])] = {
                'name': ing['Ingredient_Name'],
                'base_unit': ing['Unit'],
                'cost': float(cost_val),
                'type': ing.get('Ingredient_Type', 'RAW')
            }

    if not ingredients_df.empty:
        if current_tab == 'prep':
            filtered_ing_df = ingredients_df[ingredients_df['Ingredient_Type'] != 'PREPPED']
            dropdown_ingredients = filtered_ing_df.to_dict('records')
        else:
            dropdown_ingredients = ingredients_df.to_dict('records')

    if not products_df.empty and 'Active' in products_df.columns:
        active_prod_df = products_df[products_df['Active'].astype(str).str.upper() == 'YES']
        all_products_list = active_prod_df.to_dict('records')

    # SCENARIO A: PRODUCT RECIPES TAB
    if current_tab == 'product':
        categories = sorted(list(set(p.get('Category', 'General') for p in all_products_list if p.get('Category')))) if all_products_list else []
        
        for p in all_products_list:
            df = db.get_product_recipes(p['Product_ID'])
            items = []
            total_cost = 0.0
            
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    ing_id = str(row.get('Ingredient_ID'))
                    qty = float(pd.to_numeric(row.get('Quantity_Required', 0), errors='coerce') or 0.0)
                    unit = row.get('Unit', '')
                    
                    lookup = ing_lookup.get(ing_id, {'name': row.get('Ingredient_Name'), 'base_unit': '', 'cost': float(row.get('Cost_Per_Unit', 0) or 0.0)})
                    cost = lookup['cost']
                    total = qty * cost
                    total_cost += total

                    items.append({
                        'ID': ing_id, 'Name': lookup['name'], 'Qty': qty, 
                        'Unit': unit, 'Base_Unit': lookup['base_unit'], 'Cost': cost, 'Total': total
                    })
            
            selling_price = float(pd.to_numeric(p.get('Selling_Price', 0), errors='coerce') or 0.0)
            profit = selling_price - total_cost
            margin = (profit / selling_price * 100) if selling_price > 0 else 0.0
            
            parent_name, variant_name = resolve_parent_and_variant(p)

            recipe_obj = {
                'Product_Name': p['Product_Name'], 
                'Product_ID': p['Product_ID'], 
                'Parent_Item': parent_name,
                'Variant_Name': variant_name,
                'Category': p.get('Category', 'General') or 'General', 
                'Selling_Price': selling_price, 
                'Items': items, 'Total_Cost': total_cost, 'Profit': profit, 'Margin': margin
            }

            recipe_data.append(recipe_obj)

            if parent_name not in grouped_recipes:
                grouped_recipes[parent_name] = []
            grouped_recipes[parent_name].append(recipe_obj)

    # SCENARIO B: KITCHEN PREP SUB-RECIPES TAB
    elif current_tab == 'prep' and not ingredients_df.empty:
        prepped_ingredients_df = ingredients_df[ingredients_df['Ingredient_Type'] == 'PREPPED']
        categories = sorted(list(set(i.get('Category', 'General') for i in prepped_ingredients_df.to_dict('records') if i.get('Category')))) if not prepped_ingredients_df.empty else []
        
        for _, ing_row in prepped_ingredients_df.iterrows():
            ing_id = str(ing_row['Ingredient_ID'])
            items = []
            total_cost = 0.0
            existing_yield = 1.0
            base_unit = str(ing_row.get('Unit', 'g'))
            
            if not prep_recipes_df.empty:
                sub_formula = prep_recipes_df[prep_recipes_df['Prepped_Ingredient_ID'] == ing_id]
                
                if not sub_formula.empty and 'Batch_Yield' in sub_formula.columns:
                    try:
                        y_val = float(sub_formula['Batch_Yield'].iloc[0])
                        if y_val > 0:
                            existing_yield = y_val
                    except (ValueError, TypeError):
                        existing_yield = 1.0

                for _, row in sub_formula.iterrows():
                    raw_id = str(row.get('Raw_Ingredient_ID'))
                    qty = float(pd.to_numeric(row.get('Quantity_Required', 0), errors='coerce') or 0.0)
                    unit = row.get('Unit', '')
                    
                    lookup = ing_lookup.get(raw_id, {'name': 'Unknown Raw Material', 'base_unit': '', 'cost': 0.0})
                    cost = lookup['cost']
                    total = qty * cost
                    total_cost += total

                    items.append({
                        'ID': raw_id, 'Name': lookup['name'], 'Qty': qty, 
                        'Unit': unit, 'Base_Unit': lookup['base_unit'], 'Cost': cost, 'Total': total
                    })
            
            amortized_cost = (total_cost / existing_yield) if existing_yield > 0 else 0.0
            if pd.isna(amortized_cost) or np.isnan(amortized_cost):
                amortized_cost = 0.0

            recipe_obj = {
                'Product_Name': ing_row['Ingredient_Name'], 
                'Product_ID': ing_id, 
                'Base_Unit': base_unit,
                'Category': ing_row.get('Category', 'General') or 'General', 
                'Selling_Price': amortized_cost, 
                'Items': items, 
                'Total_Cost': total_cost, 
                'Profit': 0.0, 
                'Margin': 0.0,
                'Batch_Yield': existing_yield,
                'Amortized_Cost': amortized_cost
            }

            recipe_data.append(recipe_obj)
            grouped_recipes[ing_row['Ingredient_Name']] = [recipe_obj]

    return render_template(
        'recipes.html', 
        username=username, 
        recipe_data=recipe_data, 
        grouped_recipes=grouped_recipes,
        all_products=all_products_list,
        categories=categories,
        current_tab=current_tab,
        ingredients=dropdown_ingredients,
        unallocated_prepped_items=[i for i in ingredients_df.to_dict('records') if i.get('Ingredient_Type') == 'PREPPED'] if not ingredients_df.empty else [],
        msg=request.args.get('msg', ''),
        alert_type=request.args.get('alert_type', 'success')
    )