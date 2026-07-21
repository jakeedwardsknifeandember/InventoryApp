# routes/recipes.py - Advanced Recipes Studio Router Blueprint
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd

recipes_bp = Blueprint('recipes', __name__)

@recipes_bp.route('/portal/<username>/recipes', methods=['GET', 'POST'])
def web_recipes_tab(username):
    username = username.lower().strip()
    
    # 🔒 1. Session Authentication Check
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    # 🔒 2. Role-Based Access Guard (Restricted strictly to Platform Owner Admin)
    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Recipes management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    db = InventoryDB(f"data/client_{username}.db")
    
    # Read active tab context parameter (product vs. prep)
    current_tab = request.args.get('tab', 'product').lower().strip()
    if current_tab not in ['product', 'prep']:
        current_tab = 'product'

    # ==========================================
    # 📥 1. POST METHOD: COMMIT CONFIGURATIONS
    # ==========================================
    if request.method == 'POST':
        action = request.form.get('action_type')
        recipe_type = request.form.get('recipe_type', 'product').lower().strip()
        target_id = request.form.get('product_id')
        
        if action == 'save_recipe':
            ing_ids = request.form.getlist('ingredient_id[]')
            qtys = request.form.getlist('quantity[]')
            units = request.form.getlist('unit[]')
            
            # Fetch batch yield divisor input safely (Defaults to 1.0)
            batch_yield_val = float(request.form.get('batch_yield', 1.0) or 1.0)
            if batch_yield_val <= 0:
                batch_yield_val = 1.0
            
            recipe_items = []
            for i, q, u in zip(ing_ids, qtys, units):
                if i and q:
                    val = float(q)
                    # Normalize smaller units to base fractional metric weights (kg/L)
                    if u in ['g', 'ml']:
                        val = val / 1000.0
                    recipe_items.append({
                        'ingredient_id': i,
                        'quantity': val,
                        'unit': u
                    })
            
            if recipe_type == 'product':
                # Save traditional menu-to-component link formulas
                db.save_recipe(target_id, recipe_items)
            elif recipe_type == 'prep':
                # Direct-write process for component production sub-recipes
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
                        'Batch_Yield': batch_yield_val  # Save the divisor yield factor
                    })
                
                if new_records:
                    prep_df = pd.concat([prep_df, pd.DataFrame(new_records)], ignore_index=True)
                db.save_tab('Prep_Recipes', prep_df)
                
            db.update_all_product_costs()
            
        elif action == 'delete_recipe':
            if recipe_type == 'product':
                db.delete_recipe(target_id)
            elif recipe_type == 'prep':
                prep_df = db.read_tab('Prep_Recipes')
                if not prep_df.empty:
                    prep_df = prep_df[prep_df['Prepped_Ingredient_ID'] != target_id]
                    db.save_tab('Prep_Recipes', prep_df)
                    
            db.update_all_product_costs()
            
        return redirect(f"/portal/{username}/recipes?tab={recipe_type}")

    # ==========================================
    # 📤 2. GET METHOD: COMPUTE & RENDER WORKSPACE
    # ==========================================
    products_df = db.read_tab('Products')
    ingredients_df = db.read_tab('Ingredients')
    prep_recipes_df = db.read_tab('Prep_Recipes')
    
    # Build dynamic indexes for ingredient attributes lookup mapping
    ing_lookup = {}
    if not ingredients_df.empty:
        for _, ing in ingredients_df.iterrows():
            ing_lookup[str(ing['Ingredient_ID'])] = {
                'name': ing['Ingredient_Name'],
                'base_unit': ing['Unit'],
                'cost': float(ing['Cost_Per_Unit'] or 0),
                'type': ing.get('Ingredient_Type', 'RAW')
            }

    # Isolate dropdown ingredient scopes to clean context options
    dropdown_ingredients = []
    if not ingredients_df.empty:
        if current_tab == 'prep':
            # Sub-recipes consume RAW materials to build components
            filtered_ing_df = ingredients_df[ingredients_df['Ingredient_Type'] != 'PREPPED']
            dropdown_ingredients = filtered_ing_df.to_dict('records')
        else:
            # Menu items prioritize PREPPED components but can look up raw ingredients
            dropdown_ingredients = ingredients_df.to_dict('records')

    all_products_list = []
    if not products_df.empty and 'Active' in products_df.columns:
        active_prod_df = products_df[products_df['Active'].astype(str).str.upper() == 'YES']
        all_products_list = active_prod_df.to_dict('records')

    recipe_data = []
    categories = []

    # SCENARIO A: COMPILING RETAIL PRODUCT RECIPES DIRECTORY TAB
    if current_tab == 'product':
        categories = sorted(list(set(p.get('Category', 'General') for p in all_products_list if p.get('Category')))) if all_products_list else []
        
        for p in all_products_list:
            df = db.get_product_recipes(p['Product_ID'])
            items = []
            total_cost = 0.0
            
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    ing_id = str(row.get('Ingredient_ID'))
                    qty = float(row.get('Quantity_Required', 0))
                    unit = row.get('Unit', '')
                    
                    lookup = ing_lookup.get(ing_id, {'name': row.get('Ingredient_Name'), 'base_unit': '', 'cost': float(row.get('Cost_Per_Unit', 0))})
                    cost = lookup['cost']
                    
                    total = qty * cost
                    total_cost += total
                    
                    display_qty = qty
                    if unit in ['g', 'ml']:
                        display_qty = qty * 1000.0

                    items.append({
                        'ID': ing_id, 'Name': lookup['name'], 'Qty': display_qty, 
                        'Unit': unit, 'Base_Unit': lookup['base_unit'], 'Cost': cost, 'Total': total
                    })
            
            selling_price = float(p.get('Selling_Price', 0))
            profit = selling_price - total_cost
            margin = (profit / selling_price * 100) if selling_price > 0 else 0
            
            recipe_data.append({
                'Product_Name': p['Product_Name'], 'Product_ID': p['Product_ID'], 
                'Category': p.get('Category', 'General') or 'General', 'Selling_Price': selling_price, 
                'Items': items, 'Total_Cost': total_cost, 'Profit': profit, 'Margin': margin
            })

    # SCENARIO B: COMPILING KITCHEN PREP PRODUCTION SUB-RECIPES TAB
    elif current_tab == 'prep' and not ingredients_df.empty:
        prepped_ingredients_df = ingredients_df[ingredients_df['Ingredient_Type'] == 'PREPPED']
        categories = sorted(list(set(i.get('Category', 'General') for i in prepped_ingredients_df.to_dict('records') if i.get('Category')))) if not prepped_ingredients_df.empty else []
        
        for _, ing_row in prepped_ingredients_df.iterrows():
            ing_id = str(ing_row['Ingredient_ID'])
            items = []
            total_cost = 0.0
            existing_yield = 1.0
            
            if not prep_recipes_df.empty:
                sub_formula = prep_recipes_df[prep_recipes_df['Prepped_Ingredient_ID'] == ing_id]
                
                # Look up existing yield divisor factor if editing records
                if not sub_formula.empty and 'Batch_Yield' in sub_formula.columns:
                    try:
                        existing_yield = float(sub_formula['Batch_Yield'].iloc[0])
                    except:
                        pass

                for _, row in sub_formula.iterrows():
                    raw_id = str(row.get('Raw_Ingredient_ID'))
                    qty = float(row.get('Quantity_Required', 0))
                    unit = row.get('Unit', '')
                    
                    lookup = ing_lookup.get(raw_id, {'name': 'Unknown Raw Material', 'base_unit': '', 'cost': 0.0})
                    cost = lookup['cost']
                    
                    total = qty * cost
                    total_cost += total
                    
                    display_qty = qty
                    if unit in ['g', 'ml']:
                        display_qty = qty * 1000.0

                    items.append({
                        'ID': raw_id, 'Name': lookup['name'], 'Qty': display_qty, 
                        'Unit': unit, 'Base_Unit': lookup['base_unit'], 'Cost': cost, 'Total': total
                    })
            
            recipe_data.append({
                'Product_Name': ing_row['Ingredient_Name'], 'Product_ID': ing_id, 
                'Category': ing_row.get('Category', 'General') or 'General', 'Selling_Price': float(ing_row['Cost_Per_Unit'] or 0), 
                'Items': items, 'Total_Cost': total_cost, 'Profit': 0.0, 'Margin': 0.0,
                'Batch_Yield': existing_yield  # Pack divisor factor down to interface fields
            })

    return render_template(
        'recipes.html', 
        username=username, 
        recipe_data=recipe_data, 
        all_products=all_products_list,
        categories=categories,
        current_tab=current_tab,
        ingredients=dropdown_ingredients,
        unallocated_prepped_items=[i for i in ingredients_df.to_dict('records') if i.get('Ingredient_Type') == 'PREPPED'] if not ingredients_df.empty else []
    )