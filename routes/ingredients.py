# routes/ingredients.py
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd

ingredients_bp = Blueprint('ingredients', __name__)

@ingredients_bp.route('/portal/<username>/ingredients', methods=['GET', 'POST'])
def web_ingredients_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect('/login')
    
    db = InventoryDB(f"data/client_{username}.db")

    if request.method == 'POST':
        action = request.form.get('action_type')
        ingredient_id = request.form.get('ingredient_id')
        
        if action == 'add_ingredient':
            db.add_ingredient({
                'Ingredient_ID': db.generate_ingredient_id(),
                'Ingredient_Name': request.form.get('name'),
                'Category': request.form.get('category', 'General'),
                'Unit': request.form.get('unit', 'pcs'),
                'Current_Stock': float(request.form.get('stock', 0) or 0),
                'Min_Stock': float(request.form.get('min_stock', 0) or 0),
                'Cost_Per_Unit': float(request.form.get('cost', 0) or 0),
                'Active': 'Yes'
            })
        elif action == 'add_stock':
            additional = float(request.form.get('quantity', 0) or 0)
            df = db.read_tab('Ingredients')
            if not df.empty and ingredient_id:
                row = df[df['Ingredient_ID'] == ingredient_id]
                if not row.empty:
                    current = float(row.iloc[0].get('Current_Stock', 0) or 0)
                    db.update_ingredient(ingredient_id, {'Current_Stock': current + additional})
                    
        elif action == 'edit_ingredient':
            if ingredient_id:
                db.update_ingredient(ingredient_id, {
                    'Ingredient_Name': request.form.get('name'),
                    'Category': request.form.get('category', 'General'),
                    'Unit': request.form.get('unit'),
                    'Min_Stock': float(request.form.get('min_stock', 0) or 0),
                    'Cost_Per_Unit': float(request.form.get('cost', 0) or 0)
                })
        
        if hasattr(db, 'update_all_product_costs'):
            db.update_all_product_costs()

        return redirect(f"/portal/{username}/ingredients")

    # Data Processing
    df = db.get_inventory_status()
    if not df.empty:
        df['Min_Stock'] = pd.to_numeric(df['Min_Stock'], errors='coerce').fillna(0.0)
        df['Cost_Per_Unit'] = pd.to_numeric(df['Cost_Per_Unit'], errors='coerce').fillna(0.0)
        df['Current_Stock'] = pd.to_numeric(df['Current_Stock'], errors='coerce').fillna(0.0)
        
        # Search
        search = request.args.get('search', '').lower()
        if search:
            df = df[df['Ingredient_Name'].str.lower().str.contains(search) | 
                    df['Ingredient_ID'].str.lower().str.contains(search)]
            
        # Sorting
        sort_by = request.args.get('sort_by', 'name')
        order = request.args.get('order', 'asc')
        ascending = (order == 'asc')
        
        sort_map = {
            'name': 'Ingredient_Name', 
            'stock': 'Current_Stock', 
            'cost': 'Cost_Per_Unit',
            'id': 'Ingredient_ID',
            'category': 'Category'
        }
        col = sort_map.get(sort_by, 'Ingredient_Name')
        df = df.sort_values(col, ascending=ascending)

    ingredients_list = df.to_dict('records') if not df.empty else []
    
    return render_template('ingredients.html', 
                           username=username, 
                           ingredients=ingredients_list, 
                           current_search=request.args.get('search', ''),
                           current_sort=request.args.get('sort_by', 'name'),
                           current_order=request.args.get('order', 'asc'))