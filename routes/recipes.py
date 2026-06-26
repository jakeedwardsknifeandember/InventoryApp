# routes/recipes.py
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd

recipes_bp = Blueprint('recipes', __name__)

@recipes_bp.route('/portal/<username>/recipes', methods=['GET', 'POST'])
def web_recipes_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
    
    db = InventoryDB(f"data/client_{username}.db")

    if request.method == 'POST':
        action = request.form.get('action_type')
        product_id = request.form.get('product_id')
        
        # Synced action key listener
        if action == 'save_recipe':
            ing_ids = request.form.getlist('ingredient_id[]')
            qtys = request.form.getlist('quantity[]')
            units = request.form.getlist('unit[]')
            
            recipe_items = []
            for i, q, u in zip(ing_ids, qtys, units):
                if i and q:
                    val = float(q)
                    # Normalize sub-units to base values (kg/L) for database operations
                    if u in ['g', 'ml']:
                        val = val / 1000.0
                    recipe_items.append({
                        'ingredient_id': i,
                        'quantity': val,
                        'unit': u
                    })
            
            db.save_recipe(product_id, recipe_items)
            db.update_all_product_costs()
            
        elif action == 'delete_recipe':
            db.delete_recipe(product_id)
            db.update_all_product_costs()
            
        return redirect(f"/portal/{username}/recipes")

    # ===== GET METHOD: DISPLAY & FORMAT RECIPES =====
    products_df = db.read_tab('Products')
    ingredients_df = db.read_tab('Ingredients')
    
    # Build a fast dictionary lookup for native ingredient base units and costs
    ing_lookup = {}
    if not ingredients_df.empty:
        for _, ing in ingredients_df.iterrows():
            ing_lookup[str(ing['Ingredient_ID'])] = {
                'name': ing['Ingredient_Name'],
                'base_unit': ing['Unit'],
                'cost': float(ing['Cost_Per_Unit'] or 0)
            }

    products_list = []
    if not products_df.empty and 'Active' in products_df.columns:
        products_df = products_df[products_df['Active'].astype(str).str.upper() == 'YES']
        products_list = products_df.to_dict('records')

    categories = sorted(list(set(p.get('Category', 'General') for p in products_list if p.get('Category')))) if products_list else []

    recipe_data = []
    for p in products_list:
        df = db.get_product_recipes(p['Product_ID'])
        items = []
        total_cost = 0.0
        
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                ing_id = str(row.get('Ingredient_ID'))
                qty = float(row.get('Quantity_Required', 0))
                unit = row.get('Unit', '')
                
                # Fetch baseline cost data
                lookup = ing_lookup.get(ing_id, {'name': row.get('Ingredient_Name'), 'base_unit': '', 'cost': float(row.get('Cost_Per_Unit', 0))})
                cost = lookup['cost']
                base_unit = lookup['base_unit']
                
                total = qty * cost
                total_cost += total
                
                # REVERSE TRANSLATION: Scale fractional items back up to whole numbers for user displays
                display_qty = qty
                if unit in ['g', 'ml']:
                    display_qty = qty * 1000.0

                items.append({
                    'ID': ing_id, 
                    'Name': lookup['name'], 
                    'Qty': display_qty, 
                    'Unit': unit, 
                    'Base_Unit': base_unit,
                    'Cost': cost, 
                    'Total': total
                })
        
        selling_price = float(p.get('Selling_Price', 0))
        profit = selling_price - total_cost
        margin = (profit / selling_price * 100) if selling_price > 0 else 0
        
        recipe_data.append({
            'Product_Name': p['Product_Name'], 
            'Product_ID': p['Product_ID'], 
            'Category': p.get('Category', 'General') or 'General',
            'Selling_Price': selling_price, 
            'Items': items, 
            'Total_Cost': total_cost, 
            'Profit': profit, 
            'Margin': margin
        })

    return render_template(
        'recipes.html', 
        username=username, 
        recipe_data=recipe_data, 
        all_products=products_list,
        categories=categories,
        ingredients=ingredients_df.to_dict('records') if not ingredients_df.empty else []
    )