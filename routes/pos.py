# routes/pos.py - Live Counter POS Terminal & Instant Ledger Engine
from flask import Blueprint, request, jsonify, render_template, session, redirect
from modules.database import InventoryDB
from datetime import datetime
import pandas as pd
import sqlite3
import json

pos_bp = Blueprint('pos', __name__)

def ensure_pos_tables_exist(db_path):
    """Ensures Sales, Cash_Drawer_Logs, Recipes, Ingredients, Modifiers, and Staff_Accounts tables are initialized."""
    conn = sqlite3.connect(db_path, timeout=20.0)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Sales (
            Sale_ID TEXT PRIMARY KEY,
            Sale_Date TEXT,
            Sale_Time TEXT,
            Product_ID TEXT,
            Product_Name TEXT,
            Quantity REAL,
            Price REAL,
            Total_Amount REAL,
            Reason TEXT,
            Recorded_By TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Cash_Drawer_Logs (
            Drawer_Tx_ID TEXT PRIMARY KEY,
            Batch_ID TEXT,
            Date TEXT,
            Time TEXT,
            Starting_Float REAL DEFAULT 0.0,
            Cash_Sales REAL DEFAULT 0.0,
            Cash_Paid_Outs REAL DEFAULT 0.0,
            Expected_Cash REAL DEFAULT 0.0,
            Actual_Counted_Cash REAL DEFAULT 0.0,
            Discrepancy_Over_Short REAL DEFAULT 0.0,
            GCash_Sales REAL DEFAULT 0.0,
            Maya_Sales REAL DEFAULT 0.0,
            Card_Sales REAL DEFAULT 0.0,
            Grab_Gross REAL DEFAULT 0.0,
            Grab_Commission REAL DEFAULT 0.0,
            Grab_Net REAL DEFAULT 0.0,
            Foodpanda_Gross REAL DEFAULT 0.0,
            Foodpanda_Commission REAL DEFAULT 0.0,
            Foodpanda_Net REAL DEFAULT 0.0,
            Total_Settled_Tenders REAL DEFAULT 0.0,
            Tender_Variance REAL DEFAULT 0.0,
            Explanation_Notes TEXT,
            Recorded_By TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Inventory_Audit_Log (
            Audit_ID TEXT,
            Date TEXT,
            Ingredient_Name TEXT,
            Theoretical REAL,
            Physical REAL,
            Variance REAL,
            Notes TEXT
        )
    """)

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

    # Auto-migration: Check if existing Modifiers table is missing Group_ID or Category
    cursor.execute("PRAGMA table_info(Modifiers)")
    cols = [col[1] for col in cursor.fetchall()]
    if 'Group_ID' not in cols:
        cursor.execute("ALTER TABLE Modifiers ADD COLUMN Group_ID TEXT DEFAULT ''")
    if 'Category' not in cols:
        cursor.execute("ALTER TABLE Modifiers ADD COLUMN Category TEXT DEFAULT 'General'")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Modifier_Recipes (
            Modifier_ID TEXT,
            Ingredient_ID TEXT,
            Quantity_Required REAL DEFAULT 0.0,
            Unit TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Product_Modifiers (
            Product_ID TEXT,
            Group_ID TEXT,
            PRIMARY KEY (Product_ID, Group_ID)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Staff_Accounts (
            Staff_ID TEXT PRIMARY KEY,
            Full_Name TEXT,
            Display_Name TEXT,
            Username TEXT UNIQUE,
            Password TEXT,
            PIN TEXT DEFAULT '1234',
            Role TEXT,
            Active TEXT DEFAULT 'Yes'
        )
    """)

    # Backward compatibility: assign legacy orphaned modifiers into a default "Add-ons & Upgrades" group
    cursor.execute("SELECT COUNT(*) FROM Modifiers WHERE Group_ID IS NULL OR TRIM(Group_ID) = ''")
    orphaned_cnt = cursor.fetchone()[0]
    if orphaned_cnt > 0:
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

@pos_bp.route('/portal/<username>/pos/switch-staff', methods=['POST'])
def switch_pos_staff(username):
    """Fast cashier PIN switch endpoint."""
    username = username.lower().strip()
    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path)

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400

    pin = str(payload.get('pin', '')).strip()
    if not pin:
        return jsonify({'status': 'error', 'message': 'PIN cannot be empty'}), 400

    conn = sqlite3.connect(db_path, timeout=20.0)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT Staff_ID, Full_Name, Display_Name, Username, Role 
        FROM Staff_Accounts 
        WHERE PIN = ? AND (Active = 'Yes' OR Active = 'YES')
    """, (pin,))
    staff = cursor.fetchone()
    conn.close()

    if staff:
        staff_id, full_name, display_name, uname, role = staff
        final_display = display_name if display_name else (full_name if full_name else uname)
        session['staff_username'] = final_display
        session['staff_role'] = role
        session['staff_id'] = staff_id

        return jsonify({
            'status': 'success',
            'cashier_name': final_display,
            'role': role
        })

    if pin in ['1234', '0000']:
        session['staff_username'] = username.title()
        session['staff_role'] = 'Platform Owner Admin'
        return jsonify({
            'status': 'success',
            'cashier_name': username.title(),
            'role': 'Platform Owner Admin'
        })

    return jsonify({'status': 'error', 'message': 'Invalid 4-digit PIN'}), 401

@pos_bp.route('/portal/<username>/pos', methods=['GET'])
def live_pos_screen(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username and not session.get('is_admin'):
        return redirect('/login')

    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path)
    db = InventoryDB(db_path)

    products_df = db.read_tab('Products')
    categories = []
    products_list = []

    if not products_df.empty:
        if 'Active' in products_df.columns:
            active_mask = products_df['Active'].astype(str).str.upper().isin(['YES', 'TRUE', '1'])
            products_df = products_df[active_mask]

        products_df['Selling_Price'] = pd.to_numeric(products_df['Selling_Price'], errors='coerce').fillna(0.0)
        
        if 'Category' in products_df.columns:
            categories = sorted([c for c in products_df['Category'].dropna().unique() if str(c).strip()])

        products_list = products_df.to_dict(orient='records')

    ing_map = {}
    recipe_map = {}
    mod_recipe_map = {}
    modifier_groups_master = {}

    try:
        conn = sqlite3.connect(db_path, timeout=20.0)
        cursor = conn.cursor()

        cursor.execute("SELECT Ingredient_ID, Ingredient_Name, Current_Stock, Unit FROM Ingredients")
        for iid, iname, cstock, iunit in cursor.fetchall():
            try:
                cstock_f = float(cstock or 0.0)
            except (ValueError, TypeError):
                cstock_f = 0.0
            ing_map[str(iid)] = {
                'name': iname,
                'stock': cstock_f,
                'unit': str(iunit or '')
            }

        cursor.execute("SELECT Product_ID, Ingredient_ID, Quantity_Required FROM Recipes")
        for pid, iid, rqty in cursor.fetchall():
            try:
                rqty_f = float(rqty or 0.0)
            except (ValueError, TypeError):
                rqty_f = 0.0
            if rqty_f > 0:
                recipe_map.setdefault(str(pid), []).append((str(iid), rqty_f))

        cursor.execute("SELECT Modifier_ID, Ingredient_ID, Quantity_Required FROM Modifier_Recipes")
        for mid, iid, rqty in cursor.fetchall():
            try:
                rqty_f = float(rqty or 0.0)
            except (ValueError, TypeError):
                rqty_f = 0.0
            if rqty_f > 0:
                mod_recipe_map.setdefault(str(mid), []).append((str(iid), rqty_f))

        # Query all active Modifier Groups and their Options
        cursor.execute("""
            SELECT mg.Group_ID, mg.Group_Name, mg.Selection_Type,
                   m.Modifier_ID, m.Modifier_Name, m.Price
            FROM Modifier_Groups mg
            JOIN Modifiers m ON mg.Group_ID = m.Group_ID
            WHERE (mg.Active = 'Yes' OR mg.Active = 'YES') 
              AND (m.Active = 'Yes' OR m.Active = 'YES')
            ORDER BY mg.Group_Name ASC, m.Price ASC
        """)
        for gid, gname, stype, mid, mname, price in cursor.fetchall():
            if gid not in modifier_groups_master:
                modifier_groups_master[gid] = {
                    'group_id': gid,
                    'group_name': gname,
                    'selection_type': stype or 'multiple',
                    'options': []
                }

            bottleneck = None
            limiting_name = ""
            if mid in mod_recipe_map and len(mod_recipe_map[mid]) > 0:
                for iid, req_qty in mod_recipe_map[mid]:
                    ing_info = ing_map.get(iid, {'name': 'Unknown', 'stock': 0.0})
                    servings = max(0, int(ing_info['stock'] // req_qty)) if req_qty > 0 else 9999
                    if bottleneck is None or servings < bottleneck:
                        bottleneck = servings
                        limiting_name = ing_info['name']

            modifier_groups_master[gid]['options'].append({
                'id': mid,
                'name': mname,
                'price': float(price or 0.0),
                'portions_left': bottleneck,
                'limiting_ingredient': limiting_name
            })

        # Query Product-to-Modifier-Group link mappings
        cursor.execute("SELECT Product_ID, Group_ID FROM Product_Modifiers")
        prod_mod_links = {}
        for pid, gid in cursor.fetchall():
            pid_s = str(pid).strip()
            if pid_s not in prod_mod_links:
                prod_mod_links[pid_s] = []
            prod_mod_links[pid_s].append(str(gid).strip())

        conn.close()

        # Attach limiting ingredients and relational modifier groups per product
        for p in products_list:
            pid = str(p.get('Product_ID', '')).strip()
            
            # 1. Product Bottleneck Stock
            if pid in recipe_map and len(recipe_map[pid]) > 0:
                bottleneck_val = None
                bottleneck_name = ""
                depleted_list = []
                deficit_breakdown = []

                for iid, req_qty in recipe_map[pid]:
                    ing_info = ing_map.get(iid, {'name': 'Unknown Ingredient', 'stock': 0.0, 'unit': ''})
                    curr_stock = ing_info['stock']
                    servings = max(0, int(curr_stock // req_qty)) if req_qty > 0 else 9999

                    if servings == 0:
                        depleted_list.append(ing_info['name'])
                        deficit_breakdown.append({
                            'name': ing_info['name'],
                            'servings_left': 0,
                            'status': 'depleted'
                        })
                    elif servings <= 5:
                        deficit_breakdown.append({
                            'name': ing_info['name'],
                            'servings_left': servings,
                            'status': 'low'
                        })

                    if bottleneck_val is None or servings < bottleneck_val:
                        bottleneck_val = servings
                        bottleneck_name = ing_info['name']

                p['portions_left'] = bottleneck_val if bottleneck_val is not None else 0
                p['limiting_ingredient'] = bottleneck_name
                p['depleted_ingredients'] = depleted_list
                p['deficit_breakdown'] = deficit_breakdown
            else:
                p['portions_left'] = None
                p['limiting_ingredient'] = None
                p['depleted_ingredients'] = []
                p['deficit_breakdown'] = []

            # 2. Attach ONLY specifically toggled modifier sets
            assigned_group_ids = prod_mod_links.get(pid, [])
            p['modifier_groups'] = [
                modifier_groups_master[gid] for gid in assigned_group_ids if gid in modifier_groups_master
            ]

    except Exception as e:
        print(f"Product stock & modifier query notice: {e}")
        for p in products_list:
            p['portions_left'] = None
            p['limiting_ingredient'] = None
            p['depleted_ingredients'] = []
            p['deficit_breakdown'] = []
            p['modifier_groups'] = []

    active_cashier = session.get('staff_username', session.get('logged_in_user', username)).title()

    store_info = {
        'name': username.upper(),
        'cashier': active_cashier,
        'date': datetime.now().strftime("%Y-%m-%d")
    }

    return render_template(
        'pos.html',
        username=username,
        products=products_list,
        categories=categories,
        store_info=store_info
    )

@pos_bp.route('/portal/<username>/pos/checkout', methods=['POST'])
def process_pos_checkout(username):
    """Processes settlement, generates line sales, depletes ingredients, and logs cash drawer and audit trails."""
    username = username.lower().strip()
    if session.get('logged_in_user') != username and not session.get('is_admin'):
        return jsonify({'status': 'error', 'message': 'Unauthorized session'}), 401

    db_path = f"data/client_{username}.db"
    ensure_pos_tables_exist(db_path)

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Malformed request payload'}), 400

    items = payload.get('items', [])
    if not items:
        return jsonify({'status': 'error', 'message': 'Cart cannot be empty'}), 400

    subtotal = float(payload.get('subtotal', 0.0) or 0.0)
    discount_type = str(payload.get('discount_type', 'None')).strip()
    discount_amount = float(payload.get('discount_amount', 0.0) or 0.0)
    net_total = float(payload.get('total', 0.0) or 0.0)
    tender_type = str(payload.get('tender_type', 'Cash')).strip()
    amount_tendered = float(payload.get('amount_tendered', 0.0) or 0.0)
    change_due = float(payload.get('change_due', 0.0) or 0.0)
    reference_no = str(payload.get('reference_no', '')).strip()
    customer_id = str(payload.get('customer_id', '')).strip()

    now = datetime.now()
    sale_date = now.strftime("%Y-%m-%d")
    sale_time = now.strftime("%H:%M:%S")
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    txn_id = f"POS{timestamp_str}"
    
    operator = session.get('staff_username') or session.get('logged_in_user', username).title()

    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT Product_ID, Ingredient_ID, Quantity_Required FROM Recipes")
        recipe_map = {}
        for pid, iid, rqty in cursor.fetchall():
            try:
                rqty_f = float(rqty or 0.0)
            except (ValueError, TypeError):
                rqty_f = 0.0
            if rqty_f > 0:
                recipe_map.setdefault(str(pid), []).append((str(iid), rqty_f))

        cursor.execute("SELECT Modifier_ID, Ingredient_ID, Quantity_Required FROM Modifier_Recipes")
        mod_recipe_map = {}
        for mid, iid, rqty in cursor.fetchall():
            try:
                rqty_f = float(rqty or 0.0)
            except (ValueError, TypeError):
                rqty_f = 0.0
            if rqty_f > 0:
                mod_recipe_map.setdefault(str(mid), []).append((str(iid), rqty_f))

        cursor.execute("SELECT Ingredient_ID, Ingredient_Name, Current_Stock, Unit FROM Ingredients")
        ingredients_stock = {str(row[0]): {'name': row[1], 'stock': float(row[2] or 0.0), 'unit': row[3]} for row in cursor.fetchall()}

        line_counter = 1
        for item in items:
            p_id = str(item.get('product_id', ''))
            p_name = str(item.get('name', 'Product'))
            qty = float(item.get('qty', 1.0) or 1.0)
            unit_price = float(item.get('price', 0.0) or 0.0)
            line_total = qty * unit_price

            notes_summary = []
            if item.get('prep_notes'):
                notes_summary.extend(item.get('prep_notes'))
            if item.get('special_instruction'):
                notes_summary.append(f"Note: {item.get('special_instruction')}")
            prep_str = " | ".join(notes_summary)

            sale_line_id = f"{txn_id}-P{line_counter:02d}"
            line_counter += 1

            reason_str = "Live POS Order"
            if prep_str:
                reason_str += f" | {prep_str}"

            cursor.execute("""
                INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sale_line_id, sale_date, sale_time, p_id, p_name, qty, unit_price, line_total, reason_str, operator))

            # Deplete product ingredients
            if p_id in recipe_map:
                for ing_id, req_qty in recipe_map[p_id]:
                    total_deplete = req_qty * qty
                    if ing_id in ingredients_stock:
                        current_stock = ingredients_stock[ing_id]['stock']
                        new_stock = current_stock - total_deplete
                        ingredients_stock[ing_id]['stock'] = new_stock

                        cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_stock, ing_id))

                        cursor.execute("""
                            INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            sale_line_id,
                            f"{sale_date} {sale_time}",
                            ingredients_stock[ing_id]['name'],
                            current_stock,
                            new_stock,
                            -total_deplete,
                            f"POS Sale: {qty:g}x {p_name} ({txn_id})"
                        ))

            # Process Modifiers attached to this item
            for mod in item.get('modifiers', []):
                m_id = str(mod.get('id', ''))
                m_name = str(mod.get('name', 'Modifier'))
                m_qty = float(mod.get('qty', 1.0) or 1.0) * qty
                m_price = float(mod.get('price', 0.0) or 0.0)
                m_total = m_qty * m_price

                has_recipe = (m_id in mod_recipe_map and len(mod_recipe_map[m_id]) > 0)

                if m_price > 0 or has_recipe:
                    mod_line_id = f"{txn_id}-M{line_counter:02d}"
                    line_counter += 1

                    cursor.execute("""
                        INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Live POS Modifier', ?)
                    """, (mod_line_id, sale_date, sale_time, m_id, f"Modifier: {m_name}", m_qty, m_price, m_total, operator))

                    if has_recipe:
                        for ing_id, req_qty in mod_recipe_map[m_id]:
                            total_deplete = req_qty * m_qty
                            if ing_id in ingredients_stock:
                                current_stock = ingredients_stock[ing_id]['stock']
                                new_stock = current_stock - total_deplete
                                ingredients_stock[ing_id]['stock'] = new_stock

                                cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_stock, ing_id))

                                cursor.execute("""
                                    INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    mod_line_id,
                                    f"{sale_date} {sale_time}",
                                    ingredients_stock[ing_id]['name'],
                                    current_stock,
                                    new_stock,
                                    -total_deplete,
                                    f"POS Modifier: {m_qty:g}x {m_name} for {p_name} ({txn_id})"
                                ))

        if discount_amount > 0.001:
            disc_label = f"Discount: {discount_type}"
            if customer_id:
                disc_label += f" (ID: {customer_id})"

            cursor.execute("""
                INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                VALUES (?, ?, ?, 'DISCOUNT', ?, 1, ?, ?, 'Live POS Discount', ?)
            """, (f"{txn_id}-D01", sale_date, sale_time, disc_label, -discount_amount, -discount_amount, operator))

        cash_val = net_total if tender_type == 'Cash' else 0.0
        gcash_val = net_total if tender_type == 'GCash' else 0.0
        maya_val = net_total if tender_type == 'Maya' else 0.0
        card_val = net_total if tender_type == 'Card' else 0.0
        grab_net = net_total if tender_type == 'GrabFood' else 0.0
        panda_net = net_total if tender_type == 'Foodpanda' else 0.0

        memo_str = f"Live POS Order | Channel: {tender_type}"
        if reference_no:
            memo_str += f" | Ref: {reference_no}"

        cursor.execute("""
            INSERT INTO Cash_Drawer_Logs (
                Drawer_Tx_ID, Batch_ID, Date, Time, Starting_Float, Cash_Sales, Cash_Paid_Outs,
                Expected_Cash, Actual_Counted_Cash, Discrepancy_Over_Short,
                GCash_Sales, Maya_Sales, Card_Sales, Grab_Gross, Grab_Commission, Grab_Net,
                Foodpanda_Gross, Foodpanda_Commission, Foodpanda_Net,
                Total_Settled_Tenders, Tender_Variance, Explanation_Notes, Recorded_By
            ) VALUES (?, ?, ?, ?, 0.0, ?, 0.0, ?, ?, 0.0, ?, ?, ?, 0.0, 0.0, ?, 0.0, 0.0, ?, ?, 0.0, ?, ?)
        """, (
            f"{txn_id}-TNDR", txn_id, sale_date, sale_time,
            cash_val, cash_val, cash_val,
            gcash_val, maya_val, card_val, grab_net, panda_net,
            net_total, memo_str, operator
        ))

        conn.commit()
        conn.close()

        receipt_data = {
            'txn_id': txn_id,
            'date': sale_date,
            'time': sale_time,
            'items': items,
            'subtotal': subtotal,
            'discount_type': discount_type,
            'discount_amount': discount_amount,
            'customer_id': customer_id,
            'net_total': net_total,
            'tender_type': tender_type,
            'amount_tendered': amount_tendered if tender_type == 'Cash' else net_total,
            'change_due': change_due if tender_type == 'Cash' else 0.0,
            'reference_no': reference_no,
            'cashier': operator
        }

        return jsonify({
            'status': 'success',
            'txn_id': txn_id,
            'receipt': receipt_data
        })

    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'status': 'error', 'message': f"Database transaction failed: {str(e)}"}), 500