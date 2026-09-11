# routes/ingredients.py - Enterprise Raw Materials & Prepped Sub-Assembly Controller
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd

ingredients_bp = Blueprint('ingredients', __name__)

@ingredients_bp.route('/portal/<username>/ingredients', methods=['GET', 'POST'])
def web_ingredients_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Ingredients management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    db = InventoryDB(f"data/client_{username}.db")

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
                
            # If pack price was entered, auto-calculate exact base unit cost
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
        return redirect(f"/portal/{username}/ingredients?type=" + request.form.get('ingredient_type', 'RAW'))

    # ===== GET DATA & APPLY FILTERS =====
    df = db.get_inventory_status()
    
    categories = []
    ingredients_list = []
    total_count = 0

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
            categories = sorted([c for c in df['Category'].dropna().unique() if c])

        search = request.args.get('search', '').lower()
        status = request.args.get('status', 'All')
        category = request.args.get('category', 'All')
        sort_by = request.args.get('sort_by', 'name')
        order = request.args.get('order', 'asc')

        df = df[df['Ingredient_Type'] == current_type]

        if search:
            df = df[df['Ingredient_Name'].str.lower().str.contains(search) | 
                    df['Ingredient_ID'].str.lower().str.contains(search)]
            
        if status != 'All':
            df = df[df['Status'] == status]

        if category != 'All':
            df = df[df['Category'] == category]

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