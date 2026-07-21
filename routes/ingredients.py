# routes/ingredients.py
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd

ingredients_bp = Blueprint('ingredients', __name__)

@ingredients_bp.route('/portal/<username>/ingredients', methods=['GET', 'POST'])
def web_ingredients_tab(username):
    username = username.lower().strip()
    
    # 🔒 1. Session Authentication Check
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    # 🔒 2. Role-Based Access Guard (Restricted strictly to Platform Owner Admin)
    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Ingredients management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
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
                'Active': 'Yes',
                'Ingredient_Type': request.form.get('ingredient_type', 'RAW')  # Captures item type classification
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
                    'Cost_Per_Unit': float(request.form.get('cost', 0) or 0),
                    'Ingredient_Type': request.form.get('ingredient_type', 'RAW')  # Preserves or changes type
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

        return redirect(f"/portal/{username}/ingredients?type=" + request.form.get('ingredient_type', 'RAW'))

    # ===== GET DATA & APPLY GRID FILTERS =====
    df = db.get_inventory_status()
    
    categories = []
    ingredients_list = []
    total_count = 0

    # Read selected inner sub-tab requested (Defaults to Bulk Raw Materials)
    current_type = request.args.get('type', 'RAW').upper().strip()
    if current_type not in ['RAW', 'PREPPED']:
        current_type = 'RAW'

    if not df.empty:
        df['Min_Stock'] = pd.to_numeric(df['Min_Stock'], errors='coerce').fillna(0.0)
        df['Cost_Per_Unit'] = pd.to_numeric(df['Cost_Per_Unit'], errors='coerce').fillna(0.0)
        df['Current_Stock'] = pd.to_numeric(df['Current_Stock'], errors='coerce').fillna(0.0)
        
        if 'Ingredient_Type' not in df.columns:
            df['Ingredient_Type'] = 'RAW'
            
        # Build master category list choices dynamically from database values
        if 'Category' in df.columns:
            categories = sorted([c for c in df['Category'].dropna().unique() if c])

        # Read layout filter requests
        search = request.args.get('search', '').lower()
        status = request.args.get('status', 'All')
        category = request.args.get('category', 'All')
        sort_by = request.args.get('sort_by', 'name')
        order = request.args.get('order', 'asc')

        # Filter 1: Isolate active selection sub-tab dataset 
        df = df[df['Ingredient_Type'] == current_type]

        # Filter 2: Apply Search Rule
        if search:
            df = df[df['Ingredient_Name'].str.lower().str.contains(search) | 
                    df['Ingredient_ID'].str.lower().str.contains(search)]
            
        # Filter 3: Apply Status Rule (Normal / Low Stock / Critical)
        if status != 'All':
            df = df[df['Status'] == status]

        # Filter 4: Apply Category Selection Rule
        if category != 'All':
            df = df[df['Category'] == category]

        # Filter 5: Sorting Order Rules
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
        current_type=current_type,
        error_msg=request.args.get('error', ''),
        current_search=request.args.get('search', ''),
        current_status=request.args.get('status', 'All'),
        current_category=request.args.get('category', 'All'),
        current_sort=request.args.get('sort_by', 'name'),
        current_order=request.args.get('order', 'asc')
    )