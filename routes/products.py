# routes/products.py
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd

products_bp = Blueprint('products', __name__)

@products_bp.route('/portal/<username>/products', methods=['GET', 'POST'])
def web_products_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect('/login')
    
    db = InventoryDB(f"data/client_{username}.db")
    
    if request.method == 'POST':
        action = request.form.get('action_type')
        if action == 'add_product':
            db.add_product({
                'Product_ID': db.generate_product_id(),
                'Product_Name': request.form.get('name'),
                'Category': request.form.get('category', 'General'),
                'Selling_Price': float(request.form.get('selling_price', 0)),
                'Active': request.form.get('status', 'Yes')
            })
        elif action == 'edit_product':
            db.update_product(request.form.get('product_id'), {
                'Product_Name': request.form.get('name'),
                'Category': request.form.get('category', 'General'),
                'Selling_Price': float(request.form.get('selling_price', 0)),
                'Active': request.form.get('status', 'Yes')
            })
        # Auto-recalculate margins when prices change
        db.update_all_product_costs()
        return redirect(f"/portal/{username}/products")

    # ===== GET DATA & APPLY FILTERS =====
    # Use read_tab directly instead of get_all_products to ensure we see 'Inactive' items too
    df = db.read_tab('Products')
    
    categories = []
    products_list = []
    total_count = 0

    if not df.empty:
        # Safely convert number columns to avoid template crashes
        df['Selling_Price'] = pd.to_numeric(df['Selling_Price'], errors='coerce').fillna(0.0)
        df['Cost_Price'] = pd.to_numeric(df['Cost_Price'], errors='coerce').fillna(0.0)
        df['Margin_Percentage'] = pd.to_numeric(df['Margin_Percentage'], errors='coerce').fillna(0.0)

        # Get unique categories for the dropdown
        if 'Category' in df.columns:
            categories = sorted([c for c in df['Category'].dropna().unique() if c])

        # Get URL parameters
        search = request.args.get('search', '').lower()
        status = request.args.get('status', 'All')
        category = request.args.get('category', 'All')
        sort_by = request.args.get('sort_by', 'name')
        order = request.args.get('order', 'asc')

        # 1. Apply Search
        if search:
            df = df[df['Product_Name'].str.lower().str.contains(search) | df['Product_ID'].str.lower().str.contains(search)]

        # 2. Apply Status Filter
        if status != 'All':
            # Database stores "Yes" or "No"
            df = df[df['Active'].astype(str).str.upper() == status.upper()]

        # 3. Apply Category Filter
        if category != 'All':
            df = df[df['Category'] == category]

        # 4. Apply Sorting
        ascending = (order == 'asc')
        if sort_by == 'name':
            df = df.sort_values('Product_Name', ascending=ascending)
        elif sort_by == 'price':
            df = df.sort_values('Selling_Price', ascending=ascending)
        elif sort_by == 'margin':
            df = df.sort_values('Margin_Percentage', ascending=ascending)

        total_count = len(df)
        products_list = df.to_dict('records')

    return render_template(
        'products.html', 
        username=username, 
        products=products_list,
        categories=categories,
        total_count=total_count,
        # Pass current filters back to template so the dropdowns stay selected
        current_search=request.args.get('search', ''),
        current_status=request.args.get('status', 'All'),
        current_category=request.args.get('category', 'All'),
        current_sort=request.args.get('sort_by', 'name'),
        current_order=request.args.get('order', 'asc')
    )