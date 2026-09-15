# routes/categories.py - Full Categories Management & Automatic Product Catalog Sync
from flask import Blueprint, request, redirect, session, render_template, flash
from modules.database import InventoryDB
import pandas as pd
import sqlite3
import json
from collections import defaultdict

categories_bp = Blueprint('categories', __name__)

def sync_categories_from_products(client_db_path):
    """Scans Products and ensures every unique category exists in the Categories table."""
    try:
        conn = sqlite3.connect(client_db_path, timeout=20.0)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Categories (
                Category_ID TEXT PRIMARY KEY,
                Category_Name TEXT,
                Active TEXT DEFAULT 'Yes'
            )
        """)
        
        # 1. Fetch unique categories from products, excluding empty and 'uncategorized'
        cursor.execute("""
            SELECT DISTINCT TRIM(Category) 
            FROM Products 
            WHERE Category IS NOT NULL 
              AND TRIM(Category) != '' 
              AND LOWER(TRIM(Category)) != 'uncategorized';
        """)
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

    # Safeguard: Recognize master tenant account as Platform Owner Admin
    if not session.get('staff_role') and session.get('logged_in_user') == username:
        session['staff_role'] = 'Platform Owner Admin'

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

        # 1. ADD NEW CATEGORY (WITH COLLISION DETECTION)
        if action == 'add_category':
            category_name = request.form.get('category_name', '').strip()
            if not category_name:
                return redirect(f"/portal/{username}/categories?msg=Input Error: Category name cannot be blank.&alert_type=danger")

            try:
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()
                cursor.execute("SELECT Category_ID FROM Categories WHERE LOWER(TRIM(Category_Name)) = LOWER(TRIM(?))", (category_name,))
                if cursor.fetchone():
                    conn.close()
                    return redirect(f"/portal/{username}/categories?msg=Collision Error: A category named '{category_name}' already exists.&alert_type=danger")
                
                cursor.execute("SELECT Category_ID FROM Categories WHERE Category_ID LIKE 'CAT%';")
                existing_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
                nums = []
                for cid in existing_ids:
                    try:
                        nums.append(int(cid.replace('CAT', '')))
                    except ValueError:
                        pass
                next_num = max(nums) + 1 if nums else 1
                cat_id = f"CAT{next_num:03d}"
                cursor.execute("INSERT INTO Categories (Category_ID, Category_Name, Active) VALUES (?, ?, 'Yes')", (cat_id, category_name))
                conn.commit()
                conn.close()

                if hasattr(db, 'log_user_action'):
                    try:
                        db.log_user_action(operator, "ADD_CATEGORY", "Categories", f"Created category '{category_name}' ({cat_id})")
                    except Exception:
                        pass

                return redirect(f"/portal/{username}/categories?msg=Success: Created category '{category_name}' ({cat_id}).&alert_type=success")
            except Exception as e:
                return redirect(f"/portal/{username}/categories?msg=Database Error: {str(e)}&alert_type=danger")

        # 2. EDIT CATEGORY (WITH CASCADING TO LINKED PRODUCTS)
        elif action == 'edit_category':
            category_id = request.form.get('category_id', '').strip()
            new_name = request.form.get('category_name', '').strip()
            if not category_id or not new_name:
                return redirect(f"/portal/{username}/categories?msg=Input Error: Both Category ID and Name are required.&alert_type=danger")

            try:
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()
                
                cursor.execute("SELECT Category_ID FROM Categories WHERE LOWER(TRIM(Category_Name)) = LOWER(TRIM(?)) AND Category_ID != ?", (new_name, category_id))
                if cursor.fetchone():
                    conn.close()
                    return redirect(f"/portal/{username}/categories?msg=Collision Error: Another category named '{new_name}' already exists.&alert_type=danger")
                
                cursor.execute("SELECT Category_Name FROM Categories WHERE Category_ID = ?", (category_id,))
                old_row = cursor.fetchone()
                old_name = old_row[0] if old_row else None
                
                cursor.execute("UPDATE Categories SET Category_Name = ? WHERE Category_ID = ?", (new_name, category_id))
                
                if old_name:
                    cursor.execute("UPDATE Products SET Category = ? WHERE LOWER(TRIM(Category)) = LOWER(TRIM(?))", (new_name, old_name))
                
                conn.commit()
                conn.close()

                if hasattr(db, 'update_category'):
                    try:
                        db.update_category(category_id, new_name, username=operator)
                    except Exception:
                        pass

                if hasattr(db, 'log_user_action'):
                    try:
                        db.log_user_action(operator, "EDIT_CATEGORY", "Categories", f"Renamed category '{old_name}' to '{new_name}'")
                    except Exception:
                        pass

                return redirect(f"/portal/{username}/categories?msg=Success: Category updated to '{new_name}' and cascaded to linked products.&alert_type=success")
            except Exception as e:
                return redirect(f"/portal/{username}/categories?msg=Database Error: {str(e)}&alert_type=danger")

        # 3. DELETE CATEGORY (WITH SAFE UNLINKING TO 'Uncategorized')
        elif action == 'delete_category':
            category_id = request.form.get('category_id', '').strip()
            if category_id:
                try:
                    conn = sqlite3.connect(client_db_path, timeout=20.0)
                    cursor = conn.cursor()
                    cursor.execute("SELECT Category_Name FROM Categories WHERE Category_ID = ?", (category_id,))
                    old_row = cursor.fetchone()
                    old_name = old_row[0] if old_row else None
                    
                    cursor.execute("DELETE FROM Categories WHERE Category_ID = ?", (category_id,))
                    
                    if old_name:
                        cursor.execute("UPDATE Products SET Category = 'Uncategorized' WHERE LOWER(TRIM(Category)) = LOWER(TRIM(?))", (old_name,))
                    
                    conn.commit()
                    conn.close()

                    if hasattr(db, 'delete_category'):
                        try:
                            db.delete_category(category_id, username=operator)
                        except Exception:
                            pass

                    if hasattr(db, 'log_user_action'):
                        try:
                            db.log_user_action(operator, "DELETE_CATEGORY", "Categories", f"Deleted category '{old_name}' and moved linked items to Uncategorized")
                        except Exception:
                            pass

                    return redirect(f"/portal/{username}/categories?msg=Success: Category deleted. Any linked products moved to 'Uncategorized'.&alert_type=success")
                except Exception as e:
                    return redirect(f"/portal/{username}/categories?msg=Database Error: {str(e)}&alert_type=danger")

        # 4. CATEGORY ASSIGNMENT HUB: ATOMIC BATCH ROSTER UPDATE
        elif action == 'assign_products':
            category_id = request.form.get('category_id', '').strip()
            assigned_product_ids = request.form.getlist('assigned_product_ids[]')
            assigned_set = set(str(pid).strip() for pid in assigned_product_ids if str(pid).strip())

            if not category_id:
                return redirect(f"/portal/{username}/categories?msg=Error: Target category is required.&alert_type=danger")

            try:
                conn = sqlite3.connect(client_db_path, timeout=20.0)
                cursor = conn.cursor()

                cursor.execute("SELECT Category_Name FROM Categories WHERE Category_ID = ?", (category_id,))
                cat_row = cursor.fetchone()
                if not cat_row:
                    conn.close()
                    return redirect(f"/portal/{username}/categories?msg=Error: Category not found.&alert_type=danger")

                cat_name = cat_row[0].strip()

                # Find all products currently assigned to this category
                cursor.execute("SELECT Product_ID FROM Products WHERE LOWER(TRIM(Category)) = LOWER(TRIM(?))", (cat_name,))
                current_pids = [str(r[0]).strip() for r in cursor.fetchall() if r and r[0]]

                # Products that were unchecked -> move to 'Uncategorized'
                unassigned_count = 0
                for pid in current_pids:
                    if pid not in assigned_set:
                        cursor.execute("UPDATE Products SET Category = 'Uncategorized' WHERE Product_ID = ?", (pid,))
                        unassigned_count += 1

                # Products that were checked -> assign to cat_name
                assigned_count = 0
                for pid in assigned_set:
                    cursor.execute("UPDATE Products SET Category = ? WHERE Product_ID = ?", (cat_name, pid))
                    assigned_count += 1

                conn.commit()
                conn.close()

                if hasattr(db, 'log_user_action'):
                    try:
                        db.log_user_action(
                            operator,
                            "ASSIGN_CATEGORY_PRODUCTS",
                            "Categories",
                            f"Updated roster for category '{cat_name}': {assigned_count} items assigned, {unassigned_count} moved to Uncategorized"
                        )
                    except Exception:
                        pass

                return redirect(f"/portal/{username}/categories?msg=Success: Updated product roster for '{cat_name}' ({assigned_count} assigned, {unassigned_count} moved to Uncategorized).&alert_type=success")
            except Exception as e:
                return redirect(f"/portal/{username}/categories?msg=Database Error: {str(e)}&alert_type=danger")

        return redirect(f"/portal/{username}/categories")

    # ===== READ & COMPUTE LINKED PRODUCT COUNTS & ALL ACTIVE PRODUCTS =====
    categories_df = db.read_tab('Categories')
    products_df = db.read_tab('Products')

    category_records = []
    all_products_list = []

    if not products_df.empty:
        active_prod_mask = products_df['Active'].astype(str).str.upper().isin(['YES', 'Y', 'TRUE', '1']) if 'Active' in products_df.columns else pd.Series([True]*len(products_df))
        active_products = products_df[active_prod_mask].copy()

        for _, prow in active_products.iterrows():
            all_products_list.append({
                'Product_ID': str(prow.get('Product_ID', '')).strip(),
                'Product_Name': str(prow.get('Product_Name', '')).strip(),
                'Category': str(prow.get('Category', '') or 'Uncategorized').strip(),
                'Selling_Price': float(pd.to_numeric(prow.get('Selling_Price', 0.0), errors='coerce') or 0.0)
            })

    if not categories_df.empty:
        cat_to_products = defaultdict(list)
        for prod in all_products_list:
            c_val = prod['Category'].lower()
            if c_val:
                cat_to_products[c_val].append(prod['Product_Name'])

        for _, row in categories_df.iterrows():
            c_id = str(row.get('Category_ID', ''))
            c_name = str(row.get('Category_Name', '')).strip()
            c_key = c_name.lower()
            linked_prods = cat_to_products.get(c_key, [])
            
            category_records.append({
                'Category_ID': c_id,
                'Category_Name': c_name,
                'Active': row.get('Active', 'Yes'),
                'Linked_Count': len(linked_prods),
                'Product_Names': linked_prods
            })

    return render_template(
        'categories.html',
        username=username,
        categories=category_records,
        all_products_json=json.dumps(all_products_list),
        msg=request.args.get('msg', ''),
        alert_type=request.args.get('alert_type', 'success')
    )