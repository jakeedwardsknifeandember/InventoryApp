# routes/ingredients.py - Ingredients Module Blueprint
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB

ingredients_bp = Blueprint('ingredients', __name__)

@ingredients_bp.route('/portal/<username>/ingredients', methods=['GET', 'POST'])
def web_ingredients_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    feedback_msg, current_tab = None, request.args.get('tab', 'view')
    
    # Process core write operations from form inputs
    if request.method == 'POST' and request.form.get('action_type') == 'add_new_item':
        new_id = client_db.generate_ingredient_id()
        success, message = client_db.add_ingredient({
            'Ingredient_ID': new_id, 'Ingredient_Name': request.form.get('name'), 'Unit': request.form.get('unit'),
            'Category': request.form.get('category'), 'Current_Stock': request.form.get('stock'),
            'Min_Stock_Level': request.form.get('min_stock'), 'Cost_Per_Unit': request.form.get('cost'),
            'Supplier': request.form.get('supplier'), 'Description': request.form.get('description'), 'Active': 'Yes'
        })
        feedback_msg = f"✅ Success: Added {request.form.get('name')}!" if success else f"❌ Error: {message}"
        if success: current_tab = 'view'

    # Read live stock sets and process layout filters
    inventory_df = client_db.get_inventory_status()
    search_query = request.args.get('search', '').lower().strip()
    filter_status = request.args.get('filter_status', 'all')
    
    if not inventory_df.empty:
        if search_query: 
            inventory_df = inventory_df[inventory_df['Ingredient_Name'].str.lower().str.contains(search_query)]
        if filter_status == 'low': 
            inventory_df = inventory_df[inventory_df['Status'] == 'Low Stock']
        elif filter_status == 'critical': 
            inventory_df = inventory_df[inventory_df['Status'] == 'Critical']
            
    ingredients_list = inventory_df.to_dict(orient='records') if not inventory_df.empty else []
    
    return render_template(
        'ingredients.html',
        username=username,
        current_tab=current_tab,
        ingredients=ingredients_list,
        search_query=search_query,
        filter_status=filter_status,
        msg=feedback_msg
    )