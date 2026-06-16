# routes/inventory.py - Stock Inventory Module Blueprint
from flask import Blueprint, redirect, session, render_template
from modules.database import InventoryDB

inventory_bp = Blueprint('inventory', __name__)

@inventory_bp.route('/portal/<username>/inventory')
def web_inventory_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    inventory_df = client_db.get_inventory_status()
    inventory_list = inventory_df.to_dict(orient='records') if not inventory_df.empty else []
    
    return render_template(
        'inventory.html',
        username=username,
        inventory_status=inventory_list
    )