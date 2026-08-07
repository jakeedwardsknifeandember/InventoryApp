# routes/categories.py
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd

categories_bp = Blueprint('categories', __name__)

@categories_bp.route('/portal/<username>/categories', methods=['GET', 'POST'])
def web_categories_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Category management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    db = InventoryDB(f"data/client_{username}.db")
    
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        if action == 'add_category':
            cat_name = request.form.get('category_name', '').strip()
            success, msg = db.add_category(cat_name, username)
            flash(msg, 'success' if success else 'danger')

        elif action == 'edit_category':
            cat_id = request.form.get('category_id')
            cat_name = request.form.get('category_name', '').strip()
            success, msg = db.update_category(cat_id, cat_name, username)
            flash(msg, 'success' if success else 'danger')

        elif action == 'delete_category':
            cat_id = request.form.get('category_id')
            success, msg = db.delete_category(cat_id, username)
            flash(msg, 'info' if success else 'danger')

        return redirect(f"/portal/{username}/categories")

    # Fetch Categories and calculate product counts per category
    cats_df = db.read_tab('Categories')
    prods_df = db.read_tab('Products')
    
    categories_list = []
    if not cats_df.empty:
        for _, row in cats_df.iterrows():
            c_name = row['Category_Name']
            p_count = 0
            if not prods_df.empty and 'Category' in prods_df.columns:
                p_count = len(prods_df[prods_df['Category'] == c_name])
            
            categories_list.append({
                'Category_ID': row['Category_ID'],
                'Category_Name': c_name,
                'Product_Count': p_count
            })

    return render_template(
        'categories.html',
        username=username,
        categories=categories_list
    )