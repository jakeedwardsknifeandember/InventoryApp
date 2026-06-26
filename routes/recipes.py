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
        
        if action == 'edit_recipe':
            ing_ids = request.form.getlist('ingredient_id[]')
            qtys = request.form.getlist('quantity[]')
            units = request.form.getlist('unit[]')
            
            recipe_items = []
            for i, q, u in zip(ing_ids, qtys, units):
                if i and q:
                    val = float(q)
                    # Convert to base units for DB storage if fractional
                    if u in ['g', 'ml']:
                        val = val / 1000.0
                    recipe_items.append({'ingredient_id': str(i).strip(), 'quantity': val, 'unit': u})
            
            db.save_recipe(product_id, recipe_items)
            db.update_all_product_costs()
            
        elif action == 'delete_recipe':
            # 1. Wipe the recipe link data out of the Recipes table
            db.delete_recipe(product_id)
            # 2. Call your existing database logic to mark the product as inactive
            db.delete_product(product_id)
            # 3. Recalculate cost matrices
            db.update_all_product_costs()
            
        return redirect(f"/portal/{username}/recipes")

    products_df = db.read_tab('Products')
    ingredients_df = db.read_tab('Ingredients')
    
    # Filter out inactive products so deleted items vanish completely from view
    if not products_df.empty and 'Active' in products_df.columns:
        products_df = products_df[products_df['Active'].astype(str).str.upper() == 'YES']
    
    recipe_data = []
    if not products_df.empty:
        for _, p in products_df.iterrows():
            df = db.get_product_recipes(p['Product_ID'])
            items = []
            total_cost = 0.0
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    qty = float(row.get('Quantity_Required', 0))
                    cost = float(row.get('Cost_Per_Unit', 0))
                    total = qty * cost
                    total_cost += total
                    items.append({
                        'ID': row.get('Ingredient_ID'), 
                        'Name': row.get('Ingredient_Name'), 
                        'Qty': qty, 
                        'Unit': row.get('Unit', ''), 
                        'Cost': cost, 
                        'Total': total
                    })
            
            selling_price = float(p.get('Selling_Price', 0))
            profit = selling_price - total_cost
            margin = (profit / selling_price * 100) if selling_price > 0 else 0
            
            recipe_data.append({
                'Product_Name': p['Product_Name'], 
                'Product_ID': p['Product_ID'], 
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
        ingredients=ingredients_df.to_dict('records')
    )