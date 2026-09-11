# routes/categories.py - Full Categories Management & Automatic Product Catalog Sync
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd
import sqlite3

categories_bp = Blueprint('categories', __name__)

def sync_categories_from_products(client_db_path):
    """Scans Products and ensures every unique category exists in the Categories table."""
    try:
        conn = sqlite3.connect(client_db_path)
        cursor = conn.cursor()
        
        # 1. Fetch unique categories from active and inactive products
        cursor.execute("SELECT DISTINCT TRIM(Category) FROM Products WHERE Category IS NOT NULL AND TRIM(Category) != '';")
        product_categories = [r[0] for r in cursor.fetchall() if r and r[0]]
        
        # 2. Fetch existing category names
        cursor.execute("SELECT Category_ID, LOWER(TRIM(Category_Name)) FROM Categories;")
        existing_rows = cursor.fetchall()
        existing_names = {r[1]: r[0] for r in existing_rows if r and r[1]}
        
        # 3. Determine next CAT ID sequence
        cursor.execute("SELECT Category_ID FROM Categories WHERE Category_ID LIKE 'CAT%';")
        existing_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
        nums = []
        for cid in existing_ids:
            try:
                nums.append(int(cid.replace('CAT', '')))
            except ValueError:
                pass
        next_num = max(nums) + 1 if nums else 1

        # 4. Insert missing categories found in products
        for cat_name in product_categories:
            if cat_name.lower() not in existing_names:
                cat_id = f"CAT{next_num:03d}"
                cursor.execute(
                    "INSERT INTO Categories (Category_ID, Category_Name, Active) VALUES (?, ?, 'Yes')",
                    (cat_id, cat_name)
                )
                existing_names[cat_name.lower()] = cat_id
                next_num += 1

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error syncing categories: {e}")

@categories_bp.route('/portal/<username>/categories', methods=['GET', 'POST'])
def web_categories_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Category management is reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    client_db_path = f"data/client_{username}.db"
    db = InventoryDB(client_db_path)
    operator = session.get('logged_in_user', username)
    
    # Run automatic synchronization from products catalog
    sync_categories_from_products(client_db_path)

    if request.method == 'POST':
        action = request.form.get('action_type')

        # 1. ADD NEW CATEGORY
        if action == 'add_category':
            category_name = request.form.get('category_name', '').strip()
            if category_name:
                success, msg = db.add_category(category_name, username=operator)
                alert_type = 'success' if success else 'danger'
                return redirect(f"/portal/{username}/categories?msg={msg}&alert_type={alert_type}")

        # 2. EDIT CATEGORY
        elif action == 'edit_category':
            category_id = request.form.get('category_id')
            new_name = request.form.get('category_name', '').strip()
            if category_id and new_name:
                success, msg = db.update_category(category_id, new_name, username=operator)
                alert_type = 'success' if success else 'danger'
                return redirect(f"/portal/{username}/categories?msg={msg}&alert_type={alert_type}")

        # 3. DELETE CATEGORY
        elif action == 'delete_category':
            category_id = request.form.get('category_id')
            if category_id:
                success, msg = db.delete_category(category_id, username=operator)
                alert_type = 'success' if success else 'danger'
                return redirect(f"/portal/{username}/categories?msg={msg}&alert_type={alert_type}")

        return redirect(f"/portal/{username}/categories")

    # ===== READ & COMPUTE LINKED PRODUCT COUNTS =====
    categories_df = db.read_tab('Categories')
    products_df = db.read_tab('Products')

    category_records = []
    if not categories_df.empty:
        # Tally linked products count per category name
        product_counts = {}
        if not products_df.empty and 'Category' in products_df.columns:
            counts = products_df['Category'].astype(str).str.strip().value_counts()
            product_counts = counts.to_dict()

        for _, row in categories_df.iterrows():
            c_id = str(row.get('Category_ID', ''))
            c_name = str(row.get('Category_Name', '')).strip()
            linked_count = product_counts.get(c_name, 0)
            
            category_records.append({
                'Category_ID': c_id,
                'Category_Name': c_name,
                'Active': row.get('Active', 'Yes'),
                'Linked_Count': linked_count
            })

    return render_template(
        'categories.html',
        username=username,
        categories=category_records,
        msg=request.args.get('msg', ''),
        alert_type=request.args.get('alert_type', 'success')
    )