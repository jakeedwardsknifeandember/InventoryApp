# routes/products.py - Products Module Blueprint
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB

products_bp = Blueprint('products', __name__)

@products_bp.route('/portal/<username>/products', methods=['GET', 'POST'])
def web_products_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    feedback_msg, current_tab = None, request.args.get('tab', 'view')
    
    # Process core write operations from form payloads
    if request.method == 'POST' and request.form.get('action_type') == 'add_product':
        new_id = client_db.generate_product_id()
        success, message = client_db.add_product({
            'Product_ID': new_id, 'Product_Name': request.form.get('name'), 'Category': request.form.get('category'),
            'Selling_Price': float(request.form.get('selling_price', 0)), 'Active': 'Yes', 'Notes': request.form.get('notes', '')
        })
        feedback_msg = f"✅ Success: Added Product '{request.form.get('name')}'!" if success else f"❌ Error: {message}"
        if success: current_tab = 'view'

    # Read automated valuation profit margin matrices 
    products_df = client_db.get_all_products()
    products_list = products_df.to_dict(orient='records') if not products_df.empty else []

    return render_template(
        'products.html',
        username=username,
        current_tab=current_tab,
        products=products_list,
        msg=feedback_msg
    )