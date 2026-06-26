# routes/ingredients.py
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd

ingredients_bp = Blueprint('ingredients', __name__)

@ingredients_bp.route('/portal/<username>/ingredients', methods=['GET', 'POST'])
def web_ingredients_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
    
    db = InventoryDB(f"data/client_{username}.db")

    if request.method == 'POST':
        action = request.form.get('action_type')
        ingredient_id = request.form.get('ingredient_id')
        
        # 1. Action to register a brand new ingredient
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
            
        # 2. Action to quick-add stock quantity
        elif action == 'add_stock':
            additional = float(request.form.get('quantity', 0) or 0)
            df = db.read_tab('Ingredients')
            if not df.empty and ingredient_id:
                row = df[df['Ingredient_ID'] == ingredient_id]
                if not row.empty:
                    current = float(row.iloc[0].get('Current_Stock', 0) or 0)
                    db.update_ingredient(ingredient_id, {'Current_Stock': current + additional})
                    
        # 3. Action to modify existing ingredient details
        elif action == 'edit_ingredient':
            if ingredient_id:
                db.update_ingredient(ingredient_id, {
                    'Ingredient_Name': request.form.get('name'),
                    'Category': request.form.get('category', 'General'),
                    'Unit': request.form.get('unit'),
                    'Min_Stock': float(request.form.get('min_stock', 0) or 0),
                    'Cost_Per_Unit': float(request.form.get('cost', 0) or 0)
                })
                
        # 4. Action to permanently erase an ingredient row
        elif action == 'delete_ingredient':
            if ingredient_id:
                success, msg = db.delete_ingredient(ingredient_id)
                if not success:
                    # If blocked by recipe safety check, pass error message to screen parameters
                    return redirect(f"/portal/{username}/ingredients?error={msg}")
        
        if hasattr(db, 'update_all_product_costs'):
            db.update_all_product_costs()

        return redirect(f"/portal/{username}/ingredients")

    # ===== GET DATA & APPLY GRID FILTERS =====
    df = db.get_inventory_status()
    
    categories = []
    ingredients_list = []
    total_count = 0

    if not df.empty:
        df['Min_Stock'] = pd.to_numeric(df['Min_Stock'], errors='coerce').fillna(0.0)
        df['Cost_Per_Unit'] = pd.to_numeric(df['Cost_Per_Unit'], errors='coerce').fillna(0.0)
        df['Current_Stock'] = pd.to_numeric(df['Current_Stock'], errors='coerce').fillna(0.0)
        
        # Build master category list choices dynamically from database values
        if 'Category' in df.columns:
            categories = sorted([c for c in df['Category'].dropna().unique() if c])

        # Read layout filter requests
        search = request.args.get('search', '').lower()
        status = request.args.get('status', 'All')
        category = request.args.get('category', 'All')
        sort_by = request.args.get('sort_by', 'name')
        order = request.args.get('order', 'asc')

        # Filter 1: Apply Search Rule
        if search:
            df = df[df['Ingredient_Name'].str.lower().str.contains(search) | 
                    df['Ingredient_ID'].str.lower().str.contains(search)]
            
        # Filter 2: Apply Status Rule (Normal / Low Stock / Critical)
        if status != 'All':
            df = df[df['Status'] == status]

        # Filter 3: Apply Category Selection Rule
        if category != 'All':
            df = df[df['Category'] == category]

        # Filter 4: Sorting Order Rules
        ascending = (order == 'asc')
        sort_map = {
            'name': 'Ingredient_Name', 
            'stock': 'Current_Stock', 
            'cost': 'Cost_Per_Unit',
            'id': 'Ingredient_ID',
            'category': 'Category'
        }
        col = sort_map.get(sort_by, 'name')
        df = df.sort_values(col, ascending=ascending)

        total_count = len(df)
        ingredients_list = df.to_dict('records')

    return render_template(
        'ingredients.html', 
        username=username, 
        ingredients=ingredients_list, 
        categories=categories,
        total_count=total_count,
        error_msg=request.args.get('error', ''),
        current_search=request.args.get('search', ''),
        current_status=request.args.get('status', 'All'),
        current_category=request.args.get('category', 'All'),
        current_sort=request.args.get('sort_by', 'name'),
        current_order=request.args.get('order', 'asc')
    )