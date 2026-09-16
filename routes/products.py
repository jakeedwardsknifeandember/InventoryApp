# routes/products.py - Complete Product Catalog, Costing, Lifecycle & Relational Modifier Controller
from flask import Blueprint, request, redirect, session, render_template, flash, jsonify
from modules.database import InventoryDB
import pandas as pd
import sqlite3
import re

products_bp = Blueprint('products', __name__)

def ensure_product_modifier_tables(db_path):
    """Ensures Modifier_Groups, Modifiers (with Group_ID migration), and Product_Modifiers relational tables exist."""
    try:
        conn = sqlite3.connect(db_path, timeout=20.0)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Modifier_Groups (
                Group_ID TEXT PRIMARY KEY,
                Group_Name TEXT NOT NULL,
                Selection_Type TEXT DEFAULT 'multiple',
                Active TEXT DEFAULT 'Yes'
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Modifiers (
                Modifier_ID TEXT PRIMARY KEY,
                Group_ID TEXT DEFAULT '',
                Modifier_Name TEXT,
                Category TEXT DEFAULT 'General',
                Price REAL DEFAULT 0.0,
                Active TEXT DEFAULT 'Yes'
            )
        """)

        # Auto-migration: Check if existing Modifiers table is missing Group_ID column
        cursor.execute("PRAGMA table_info(Modifiers)")
        cols = [col[1] for col in cursor.fetchall()]
        if 'Group_ID' not in cols:
            cursor.execute("ALTER TABLE Modifiers ADD COLUMN Group_ID TEXT DEFAULT ''")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Product_Modifiers (
                Product_ID TEXT,
                Group_ID TEXT,
                PRIMARY KEY (Product_ID, Group_ID)
            )
        """)

        # Auto-assign legacy orphaned modifiers into a default "Add-ons & Upgrades" group
        cursor.execute("SELECT COUNT(*) FROM Modifiers WHERE Group_ID IS NULL OR TRIM(Group_ID) = ''")
        orphaned_count = cursor.fetchone()[0]
        if orphaned_count > 0:
            cursor.execute("SELECT Group_ID FROM Modifier_Groups WHERE Group_Name = 'Add-ons & Upgrades'")
            row = cursor.fetchone()
            if row:
                grp_id = row[0]
            else:
                grp_id = 'MODGRP001'
                cursor.execute("INSERT OR IGNORE INTO Modifier_Groups (Group_ID, Group_Name, Selection_Type, Active) VALUES (?, 'Add-ons & Upgrades', 'multiple', 'Yes')", (grp_id,))
            cursor.execute("UPDATE Modifiers SET Group_ID = ? WHERE Group_ID IS NULL OR TRIM(Group_ID) = ''", (grp_id,))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Product modifier tables migration error: {e}")

def heal_product_variants(db_path):
    """Automatically repairs any NULL, blank, or 'None' strings in Parent_Item and Variant_Name."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE Products 
            SET Variant_Name = 'Regular' 
            WHERE Variant_Name IS NULL 
               OR TRIM(Variant_Name) = '' 
               OR LOWER(TRIM(Variant_Name)) IN ('none', 'nan', 'null');
        """)
        cursor.execute("""
            UPDATE Products 
            SET Parent_Item = Product_Name 
            WHERE Parent_Item IS NULL 
               OR TRIM(Parent_Item) = '' 
               OR LOWER(TRIM(Parent_Item)) IN ('none', 'nan', 'null');
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Product variant healing warning: {e}")

def sync_product_categories(db_path):
    """Automatically synchronizes unique product categories into the Categories table."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT Category FROM Products WHERE Category IS NOT NULL AND TRIM(Category) != '';")
        prod_cats = [r[0].strip() for r in cursor.fetchall() if r and r[0]]
        
        cursor.execute("SELECT Category_Name FROM Categories;")
        existing_cats = [r[0].strip().lower() for r in cursor.fetchall() if r and r[0]]
        
        cursor.execute("SELECT Category_ID FROM Categories WHERE Category_ID LIKE 'CAT%';")
        existing_ids = [r[0] for r in cursor.fetchall() if r and r[0]]
        nums = []
        for cid in existing_ids:
            try:
                nums.append(int(cid.replace('CAT', '')))
            except ValueError:
                pass
        next_num = max(nums) + 1 if nums else 1

        for cat in prod_cats:
            if cat.lower() not in existing_cats:
                cat_id = f"CAT{next_num:03d}"
                cursor.execute("INSERT INTO Categories (Category_ID, Category_Name, Active) VALUES (?, ?, 'Yes')", (cat_id, cat))
                existing_cats.append(cat.lower())
                next_num += 1
                
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Category auto-sync error: {e}")

@products_bp.route('/portal/<username>/products/inline-update', methods=['POST'])
def inline_update_product(username):
    """Instant AJAX endpoint for inline editing Selling Price or Category directly from the catalog table."""
    username = username.lower().strip()
    if session.get('logged_in_user') != username and not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    
    if session.get('staff_role') != 'Platform Owner Admin':
        return jsonify({'status': 'error', 'message': 'Strictly reserved for Platform Owner Admin'}), 403

    client_db_path = f"data/client_{username}.db"
    db = InventoryDB(client_db_path)

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Malformed JSON payload'}), 400

    update_type = payload.get('type')

    # 1. INLINE UPDATE SELLING PRICE
    if update_type == 'price':
        product_id = str(payload.get('product_id', '')).strip()
        try:
            new_price = float(payload.get('price', 0.0))
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'message': 'Invalid price value'}), 400

        if new_price < 0:
            return jsonify({'status': 'error', 'message': 'Price cannot be negative'}), 400

        conn = sqlite3.connect(client_db_path, timeout=20.0)
        cursor = conn.cursor()

        cursor.execute("SELECT Cost_Price FROM Products WHERE Product_ID = ?", (product_id,))
        row = cursor.fetchone()
        cost_price = float(row[0] or 0.0) if row else 0.0

        margin_pct = ((new_price - cost_price) / new_price * 100.0) if new_price > 0 else 0.0

        cursor.execute("""
            UPDATE Products 
            SET Selling_Price = ?, Margin_Percentage = ? 
            WHERE Product_ID = ?
        """, (new_price, margin_pct, product_id))

        conn.commit()
        conn.close()

        db.update_all_product_costs()

        return jsonify({
            'status': 'success',
            'product_id': product_id,
            'selling_price': new_price,
            'cost_price': cost_price,
            'margin_pct': margin_pct
        })

    # 2. INLINE UPDATE CATEGORY
    elif update_type == 'category':
        new_category = str(payload.get('category', '')).strip()
        target_type = payload.get('target_type', 'product')
        parent_item = str(payload.get('parent_item', '')).strip()
        product_id = str(payload.get('product_id', '')).strip()

        if not new_category:
            return jsonify({'status': 'error', 'message': 'Category name cannot be empty'}), 400

        conn = sqlite3.connect(client_db_path, timeout=20.0)
        cursor = conn.cursor()

        if target_type == 'parent' and parent_item:
            cursor.execute("""
                UPDATE Products 
                SET Category = ? 
                WHERE LOWER(TRIM(Parent_Item)) = LOWER(TRIM(?))
            """, (new_category, parent_item))
        elif product_id:
            cursor.execute("""
                UPDATE Products 
                SET Category = ? 
                WHERE Product_ID = ?
            """, (new_category, product_id))

        conn.commit()
        conn.close()

        sync_product_categories(client_db_path)

        return jsonify({
            'status': 'success',
            'new_category': new_category,
            'message': f"Category updated to '{new_category}' successfully."
        })

    return jsonify({'status': 'error', 'message': 'Invalid update type'}), 400

@products_bp.route('/portal/<username>/products', methods=['GET', 'POST'])
def web_products_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    if session.get('staff_role') != 'Platform Owner Admin':
        flash('Unauthorized access: Products management is strictly reserved for Platform Owner Admins.', 'danger')
        return redirect(f"/portal/{username}")
    
    client_db_path = f"data/client_{username}.db"
    db = InventoryDB(client_db_path)
    ensure_product_modifier_tables(client_db_path)
    heal_product_variants(client_db_path)
    sync_product_categories(client_db_path)
    
    current_status = request.args.get('status', 'Yes')
    operator = session.get('logged_in_user', username)
    
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        # 1. ACTION: ADD NEW PRODUCT OR VARIANT
        if action == 'add_product':
            parent_item = request.form.get('parent_item', '').strip()
            variant_name = request.form.get('variant_name', 'Regular').strip()
            
            if not variant_name or variant_name.lower() in ['none', 'nan', 'null', '']:
                variant_name = 'Regular'
            
            if not parent_item:
                parent_item = request.form.get('name', '').strip() 
                
            product_name = f"{parent_item} ({variant_name})" if variant_name.lower() != 'regular' else parent_item
            
            df_check = db.read_tab('Products')
            if not df_check.empty and 'Parent_Item' in df_check.columns and 'Variant_Name' in df_check.columns:
                conflict = df_check[(df_check['Parent_Item'].astype(str).str.lower() == parent_item.lower()) & 
                                    (df_check['Variant_Name'].astype(str).str.lower() == variant_name.lower())]
                if not conflict.empty:
                    return redirect(f"/portal/{username}/products?error=Variant '{variant_name}' already exists under the '{parent_item}' product line.&status={current_status}")
                    
            new_prod_id = db.generate_product_id()
            success, msg = db.add_product({
                'Product_ID': new_prod_id,
                'Product_Name': product_name,
                'Parent_Item': parent_item,
                'Variant_Name': variant_name,
                'Category': request.form.get('category', 'General'),
                'Selling_Price': float(request.form.get('selling_price', 0) or 0.0),
                'Active': request.form.get('status', 'Yes')
            }, username=operator)

            # Save toggled modifier sets
            if success:
                selected_mod_groups = request.form.getlist('modifier_groups[]')
                if selected_mod_groups:
                    conn = sqlite3.connect(client_db_path, timeout=20.0)
                    cursor = conn.cursor()
                    for gid in selected_mod_groups:
                        cursor.execute("INSERT OR IGNORE INTO Product_Modifiers (Product_ID, Group_ID) VALUES (?, ?)", (new_prod_id, gid))
                    conn.commit()
                    conn.close()
            
            db.update_all_product_costs()
            heal_product_variants(client_db_path)
            sync_product_categories(client_db_path)
            alert_type = 'success' if success else 'danger'
            return redirect(f"/portal/{username}/products?status=Yes&msg={msg}&alert_type={alert_type}")
            
        # 2. ACTION: EDIT EXISTING PRODUCT
        elif action == 'edit_product':
            parent_item = request.form.get('parent_item', '').strip()
            variant_name = request.form.get('variant_name', 'Regular').strip()
            product_id = request.form.get('product_id')
            
            if not variant_name or variant_name.lower() in ['none', 'nan', 'null', '']:
                variant_name = 'Regular'
            
            if not parent_item:
                parent_item = request.form.get('name', '').strip() 
                
            product_name = f"{parent_item} ({variant_name})" if variant_name.lower() != 'regular' else parent_item
            
            df_check = db.read_tab('Products')
            if not df_check.empty and 'Parent_Item' in df_check.columns and 'Variant_Name' in df_check.columns:
                other_prods = df_check[df_check['Product_ID'] != product_id]
                conflict = other_prods[(other_prods['Parent_Item'].astype(str).str.lower() == parent_item.lower()) & 
                                       (other_prods['Variant_Name'].astype(str).str.lower() == variant_name.lower())]
                if not conflict.empty:
                    return redirect(f"/portal/{username}/products?error=Another variant named '{variant_name}' already exists under the '{parent_item}' product line.&status={current_status}")
                    
            success, msg = db.update_product(product_id, {
                'Product_Name': product_name,
                'Parent_Item': parent_item,
                'Variant_Name': variant_name,
                'Category': request.form.get('category', 'General'),
                'Selling_Price': float(request.form.get('selling_price', 0) or 0.0),
                'Active': request.form.get('status', 'Yes')
            }, username=operator)

            # Update toggled modifier sets
            selected_mod_groups = request.form.getlist('modifier_groups[]')
            conn = sqlite3.connect(client_db_path, timeout=20.0)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Product_Modifiers WHERE Product_ID = ?", (product_id,))
            for gid in selected_mod_groups:
                cursor.execute("INSERT OR IGNORE INTO Product_Modifiers (Product_ID, Group_ID) VALUES (?, ?)", (product_id, gid))
            conn.commit()
            conn.close()
            
            db.update_all_product_costs()
            heal_product_variants(client_db_path)
            sync_product_categories(client_db_path)
            alert_type = 'success' if success else 'danger'
            return redirect(f"/portal/{username}/products?status={current_status}&msg={msg}&alert_type={alert_type}")
            
        # 3. ACTION: DELETE PRODUCT
        elif action == 'delete_product':
            product_id = request.form.get('product_id')
            success, msg = db.delete_product(product_id, username=operator)
            
            conn = sqlite3.connect(client_db_path, timeout=20.0)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Product_Modifiers WHERE Product_ID = ?", (product_id,))
            conn.commit()
            conn.close()

            db.update_all_product_costs()
            alert_type = 'success' if success else 'danger'
            return redirect(f"/portal/{username}/products?status={current_status}&msg={msg}&alert_type={alert_type}")

        # 4. ACTION: REACTIVATE PRODUCT
        elif action == 'reactivate_product':
            product_id = request.form.get('product_id')
            if hasattr(db, 'reactivate_product'):
                success, msg = db.reactivate_product(product_id, username=operator)
            else:
                success, msg = db.update_product(product_id, {'Active': 'Yes'}, username=operator)
                if success:
                    msg = f"Product {product_id} reactivated and restored to active menu."
            db.update_all_product_costs()
            alert_type = 'success' if success else 'danger'
            return redirect(f"/portal/{username}/products?status=Yes&msg={msg}&alert_type={alert_type}")

        return redirect(f"/portal/{username}/products?status={current_status}")

    # ===== FETCH MODIFIER GROUPS & PRODUCT MAPPINGS =====
    all_modifier_groups = []
    product_modifiers_map = {}

    conn = sqlite3.connect(client_db_path, timeout=20.0)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT mg.Group_ID, mg.Group_Name, mg.Selection_Type, COUNT(m.Modifier_ID)
        FROM Modifier_Groups mg
        LEFT JOIN Modifiers m ON mg.Group_ID = m.Group_ID AND (m.Active = 'Yes' OR m.Active = 'YES')
        WHERE (mg.Active = 'Yes' OR mg.Active = 'YES')
        GROUP BY mg.Group_ID, mg.Group_Name, mg.Selection_Type
        ORDER BY mg.Group_Name ASC
    """)
    for gid, gname, stype, opt_cnt in cursor.fetchall():
        all_modifier_groups.append({
            'Group_ID': gid,
            'Group_Name': gname,
            'Selection_Type': stype or 'multiple',
            'Option_Count': opt_cnt
        })

    cursor.execute("SELECT Product_ID, Group_ID FROM Product_Modifiers")
    for pid, gid in cursor.fetchall():
        pid_s = str(pid).strip()
        if pid_s not in product_modifiers_map:
            product_modifiers_map[pid_s] = []
        product_modifiers_map[pid_s].append(str(gid).strip())
    conn.close()

    # ===== GET DATA & APPLY FILTERS =====
    df = db.read_tab('Products')
    
    all_products_raw = []
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
            categories = sorted([c for c in df['Category'].dropna().unique() if str(c).strip()])

        if 'Parent_Item' not in df.columns:
            df['Parent_Item'] = None
        if 'Variant_Name' not in df.columns:
            df['Variant_Name'] = 'Regular'

        for idx, row in df.iterrows():
            raw_p = row.get('Parent_Item')
            raw_v = row.get('Variant_Name')
            raw_name = str(row.get('Product_Name') or '').strip()

            v_str = str(raw_v).strip() if pd.notna(raw_v) else ''
            if v_str.lower() in ['', 'nan', 'none', 'null']:
                v_str = 'Regular'

            p_str = str(raw_p).strip() if pd.notna(raw_p) else ''
            if p_str.lower() in ['', 'nan', 'none', 'null']:
                match = re.match(r'^(Hot|Iced|Warm|Cold)\s*[-–:]\s*(.+)$', raw_name, re.IGNORECASE)
                if match:
                    p_str = match.group(2).strip()
                    if v_str == 'Regular':
                        v_str = match.group(1).capitalize()
                else:
                    p_str = raw_name

            df.at[idx, 'Parent_Item'] = p_str
            df.at[idx, 'Variant_Name'] = v_str

        all_products_raw = df.to_dict('records')

        search = request.args.get('search', '').lower()
        status = request.args.get('status', 'Yes')
        category = request.args.get('category', 'All')
        sort_by = request.args.get('sort_by', 'id')
        order = request.args.get('order', 'asc')

        if search:
            df = df[df['Product_Name'].astype(str).str.lower().str.contains(search) | 
                    df['Product_ID'].astype(str).str.lower().str.contains(search) |
                    df['Parent_Item'].astype(str).str.lower().str.contains(search)]

        if status != 'All':
            df = df[df['Active'].astype(str).str.upper() == status.upper()]

        if category != 'All':
            df = df[df['Category'] == category]

        # CLICKABLE COLUMN HEADER SORTING HANDLERS
        ascending = (order == 'asc')
        if sort_by == 'id':
            df = df.sort_values('Product_ID', ascending=ascending)
        elif sort_by == 'name':
            df = df.sort_values(['Parent_Item', 'Variant_Name'], ascending=[ascending, True])
        elif sort_by == 'category':
            df = df.sort_values(['Category', 'Parent_Item'], ascending=[ascending, True])
        elif sort_by == 'price':
            df = df.sort_values('Selling_Price', ascending=ascending)
        elif sort_by == 'cost':
            df = df.sort_values('Cost_Price', ascending=ascending)
        elif sort_by == 'margin':
            df = df.sort_values('Margin_Percentage', ascending=ascending)
        elif sort_by == 'food_cost':
            df = df.sort_values('Food_Cost_Pct', ascending=ascending)
        elif sort_by == 'status':
            df = df.sort_values(['Active', 'Parent_Item'], ascending=[ascending, True])
        else:
            df = df.sort_values('Product_ID', ascending=True)

        total_count = len(df)
        
        products_list = df.to_dict('records')
        for p in products_list:
            parent = p.get('Parent_Item') or p.get('Product_Name') or 'General Item'
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
        all_modifier_groups=all_modifier_groups,
        product_modifiers_map=product_modifiers_map,
        total_count=total_count,
        error_msg=request.args.get('error', ''),
        msg=request.args.get('msg', ''),
        alert_type=request.args.get('alert_type', 'success'),
        current_search=request.args.get('search', ''),
        current_status=status,
        current_category=category,
        current_sort=sort_by,
        current_order=order
    )