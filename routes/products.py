# routes/products.py
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd

products_bp = Blueprint('products', __name__)

@products_bp.route('/portal/<username>/products', methods=['GET', 'POST'])
def web_products_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Products management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    db = InventoryDB(f"data/client_{username}.db")
    
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        # 1. Action to add a product (Now tracking Parent and Variant structures)
        if action == 'add_product':
            parent_item = request.form.get('parent_item', '').strip()
            variant_name = request.form.get('variant_name', 'Regular').strip()
            
            if not parent_item:
                parent_item = request.form.get('name', '').strip() 
                
            product_name = f"{parent_item} ({variant_name})" if variant_name.lower() != 'regular' else parent_item
            
            df_check = db.read_tab('Products')
            if not df_check.empty and 'Parent_Item' in df_check.columns and 'Variant_Name' in df_check.columns:
                conflict = df_check[(df_check['Parent_Item'].str.lower() == parent_item.lower()) & 
                                    (df_check['Variant_Name'].str.lower() == variant_name.lower())]
                if not conflict.empty:
                    return redirect(f"/portal/{username}/products?error=Variant '{variant_name}' already exists under the '{parent_item}' product line.")
                    
            db.add_product({
                'Product_ID': db.generate_product_id(),
                'Product_Name': product_name,
                'Parent_Item': parent_item,
                'Variant_Name': variant_name,
                'Category': request.form.get('category', 'General'),
                'Selling_Price': float(request.form.get('selling_price', 0)),
                'Active': request.form.get('status', 'Yes')
            })
            
        # 2. Action to edit an existing product
        elif action == 'edit_product':
            parent_item = request.form.get('parent_item', '').strip()
            variant_name = request.form.get('variant_name', 'Regular').strip()
            product_id = request.form.get('product_id')
            
            if not parent_item:
                parent_item = request.form.get('name', '').strip() 
                
            product_name = f"{parent_item} ({variant_name})" if variant_name.lower() != 'regular' else parent_item
            
            df_check = db.read_tab('Products')
            if not df_check.empty and 'Parent_Item' in df_check.columns and 'Variant_Name' in df_check.columns:
                other_prods = df_check[df_check['Product_ID'] != product_id]
                conflict = other_prods[(other_prods['Parent_Item'].str.lower() == parent_item.lower()) & 
                                       (other_prods['Variant_Name'].str.lower() == variant_name.lower())]
                if not conflict.empty:
                    return redirect(f"/portal/{username}/products?error=Another variant named '{variant_name}' already exists under the '{parent_item}' product line.")
                    
            db.update_product(product_id, {
                'Product_Name': product_name,
                'Parent_Item': parent_item,
                'Variant_Name': variant_name,
                'Category': request.form.get('category', 'General'),
                'Selling_Price': float(request.form.get('selling_price', 0)),
                'Active': request.form.get('status', 'Yes')
            })
            
        # 3. Action to completely delete a product
        elif action == 'delete_product':
            product_id = request.form.get('product_id')
            db.delete_product(product_id)

        db.update_all_product_costs()
        return redirect(f"/portal/{username}/products")

    # ===== GET DATA & APPLY FILTERS =====
    df = db.read_tab('Products')
    
    all_products_raw = []
    if not df.empty:
        all_products_raw = df.to_dict('records')
    
    categories = []
    grouped_products = {}
    unique_parents = []
    total_count = 0

    if not df.empty:
        df['Selling_Price'] = pd.to_numeric(df['Selling_Price'], errors='coerce').fillna(0.0)
        df['Cost_Price'] = pd.to_numeric(df['Cost_Price'], errors='coerce').fillna(0.0)
        df['Margin_Percentage'] = pd.to_numeric(df['Margin_Percentage'], errors='coerce').fillna(0.0)

        df['Cash_Profit'] = df['Selling_Price'] - df['Cost_Price']
        df['Food_Cost_Pct'] = 0.0
        mask = df['Selling_Price'] > 0
        df.loc[mask, 'Food_Cost_Pct'] = (df.loc[mask, 'Cost_Price'] / df.loc[mask, 'Selling_Price']) * 100.0

        if 'Category' in df.columns:
            categories = sorted([c for c in df['Category'].dropna().unique() if c])

        # Safety catch for legacy un-migrated databases
        if 'Parent_Item' not in df.columns:
            df['Parent_Item'] = df['Product_Name']
            df['Variant_Name'] = 'Regular'
        else:
            # FIXED: Using .mask() instead of passing a Series into .replace()
            df['Parent_Item'] = df['Parent_Item'].fillna(df['Product_Name'])
            df['Parent_Item'] = df['Parent_Item'].mask(df['Parent_Item'] == '', df['Product_Name'])
            
            df['Variant_Name'] = df['Variant_Name'].fillna('Regular')
            df['Variant_Name'] = df['Variant_Name'].mask(df['Variant_Name'] == '', 'Regular')

        search = request.args.get('search', '').lower()
        status = request.args.get('status', 'All')
        category = request.args.get('category', 'All')
        sort_by = request.args.get('sort_by', 'name')
        order = request.args.get('order', 'asc')

        if search:
            df = df[df['Product_Name'].str.lower().str.contains(search) | df['Product_ID'].str.lower().str.contains(search)]

        if status != 'All':
            df = df[df['Active'].astype(str).str.upper() == status.upper()]

        if category != 'All':
            df = df[df['Category'] == category]

        ascending = (order == 'asc')
        if sort_by == 'name':
            df = df.sort_values('Product_Name', ascending=ascending)
        elif sort_by == 'price':
            df = df.sort_values('Selling_Price', ascending=ascending)
        elif sort_by == 'margin':
            df = df.sort_values('Margin_Percentage', ascending=ascending)
        elif sort_by == 'food_cost':
            df = df.sort_values('Food_Cost_Pct', ascending=ascending)

        total_count = len(df)
        
        products_list = df.to_dict('records')
        for p in products_list:
            parent = p.get('Parent_Item', p['Product_Name'])
            if parent not in grouped_products:
                grouped_products[parent] = []
            grouped_products[parent].append(p)
            
        unique_parents = sorted(list(set(df['Parent_Item'].dropna().tolist())))

    return render_template(
        'products.html', 
        username=username, 
        grouped_products=grouped_products,
        unique_parents=unique_parents,
        all_products_raw=all_products_raw,
        categories=categories,
        total_count=total_count,
        error_msg=request.args.get('error', ''),
        current_search=request.args.get('search', ''),
        current_status=request.args.get('status', 'All'),
        current_category=request.args.get('category', 'All'),
        current_sort=request.args.get('sort_by', 'name'),
        current_order=request.args.get('order', 'asc')
    )