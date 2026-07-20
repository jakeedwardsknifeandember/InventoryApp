# routes/products.py
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd

products_bp = Blueprint('products', __name__)

@products_bp.route('/portal/<username>/products', methods=['GET', 'POST'])
def web_products_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
    
    db = InventoryDB(f"data/client_{username}.db")
    
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        # 1. Action to add a product
        if action == 'add_product':
            product_name = request.form.get('name').strip()
            df_check = db.read_tab('Products')
            if not df_check.empty and 'Product_Name' in df_check.columns:
                if product_name.lower() in [str(n).lower().strip() for n in df_check['Product_Name'].dropna()]:
                    return redirect(f"/portal/{username}/products?error=A product named '{product_name}' already exists.")
                    
            db.add_product({
                'Product_ID': db.generate_product_id(),
                'Product_Name': product_name,
                'Category': request.form.get('category', 'General'),
                'Selling_Price': float(request.form.get('selling_price', 0)),
                'Active': request.form.get('status', 'Yes')
            })
            
        # 2. Action to edit an existing product
        elif action == 'edit_product':
            product_name = request.form.get('name').strip()
            product_id = request.form.get('product_id')
            df_check = db.read_tab('Products')
            if not df_check.empty and 'Product_Name' in df_check.columns:
                other_prods = df_check[df_check['Product_ID'] != product_id]
                if product_name.lower() in [str(n).lower().strip() for n in other_prods['Product_Name'].dropna()]:
                    return redirect(f"/portal/{username}/products?error=Another product named '{product_name}' already exists.")
                    
            db.update_product(product_id, {
                'Product_Name': product_name,
                'Category': request.form.get('category', 'General'),
                'Selling_Price': float(request.form.get('selling_price', 0)),
                'Active': request.form.get('status', 'Yes')
            })
            
        # 3. Action to completely delete a product
        elif action == 'delete_product':
            product_id = request.form.get('product_id')
            db.delete_product(product_id)

        # Auto-recalculate margins when prices or data change
        db.update_all_product_costs()
        return redirect(f"/portal/{username}/products")

    # ===== GET DATA & APPLY FILTERS =====
    df = db.read_tab('Products')
    
    all_products_raw = []
    if not df.empty:
        all_products_raw = df.to_dict('records')
    
    categories = []
    products_list = []
    total_count = 0

    if not df.empty:
        # Safely convert numeric columns
        df['Selling_Price'] = pd.to_numeric(df['Selling_Price'], errors='coerce').fillna(0.0)
        df['Cost_Price'] = pd.to_numeric(df['Cost_Price'], errors='coerce').fillna(0.0)
        df['Margin_Percentage'] = pd.to_numeric(df['Margin_Percentage'], errors='coerce').fillna(0.0)

        # Compute Cash Profit Spread and Food Cost %
        df['Cash_Profit'] = df['Selling_Price'] - df['Cost_Price']
        df['Food_Cost_Pct'] = 0.0
        mask = df['Selling_Price'] > 0
        df.loc[mask, 'Food_Cost_Pct'] = (df.loc[mask, 'Cost_Price'] / df.loc[mask, 'Selling_Price']) * 100.0

        if 'Category' in df.columns:
            categories = sorted([c for c in df['Category'].dropna().unique() if c])

        # Get URL filtering parameters
        search = request.args.get('search', '').lower()
        status = request.args.get('status', 'All')
        category = request.args.get('category', 'All')
        sort_by = request.args.get('sort_by', 'name')
        order = request.args.get('order', 'asc')

        # Filter Rule 1: Search
        if search:
            df = df[df['Product_Name'].str.lower().str.contains(search) | df['Product_ID'].str.lower().str.contains(search)]

        # Filter Rule 2: Status Filter
        if status != 'All':
            df = df[df['Active'].astype(str).str.upper() == status.upper()]

        # Filter Rule 3: Category Filter
        if category != 'All':
            df = df[df['Category'] == category]

        # Filter Rule 4: Sorting Matrix
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

    return render_template(
        'products.html', 
        username=username, 
        products=products_list,
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