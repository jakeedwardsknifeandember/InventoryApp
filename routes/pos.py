# routes/pos.py - Live Counter POS Terminal & Instant Ledger Engine
from flask import Blueprint, request, jsonify, render_template, session, redirect
from modules.database import InventoryDB
from datetime import datetime
import pandas as pd
import sqlite3
import json

pos_bp = Blueprint('pos', __name__)

def ensure_pos_tables_exist(db_path):
    """Ensures Sales, Cash_Drawer_Logs, Recipes, and Ingredients tables are initialized."""
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
            Starting_Float REAL,
            Cash_Sales REAL,
            Cash_Paid_Outs REAL,
            Expected_Cash REAL,
            Actual_Counted_Cash REAL,
            Discrepancy_Over_Short REAL,
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
    
    conn.commit()
    conn.close()

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

    # Calculate limiting bottleneck and deficit items
    try:
        conn = sqlite3.connect(db_path, timeout=20.0)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Recipes'")
        has_recipes = cursor.fetchone() is not None

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Ingredients'")
        has_ingredients = cursor.fetchone() is not None

        recipe_map = {}
        if has_recipes:
            cursor.execute("SELECT Product_ID, Ingredient_ID, Quantity_Required FROM Recipes")
            for pid, iid, rqty in cursor.fetchall():
                try:
                    rqty_f = float(rqty or 0.0)
                except (ValueError, TypeError):
                    rqty_f = 0.0
                if rqty_f > 0:
                    recipe_map.setdefault(str(pid), []).append((str(iid), rqty_f))

        ing_map = {}
        if has_ingredients:
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

        conn.close()

        for p in products_list:
            pid = str(p.get('Product_ID', ''))
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

    except Exception:
        for p in products_list:
            p['portions_left'] = None
            p['limiting_ingredient'] = None
            p['depleted_ingredients'] = []
            p['deficit_breakdown'] = []

    # Fetch available modifiers
    modifiers_list = []
    try:
        conn = sqlite3.connect(db_path, timeout=20.0)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifiers'")
        if cursor.fetchone():
            mod_df = pd.read_sql_query("SELECT * FROM Modifiers WHERE Active = 'Yes' OR Active = 'YES'", conn)
            modifiers_list = mod_df.to_dict(orient='records')
        conn.close()
    except Exception:
        modifiers_list = []

    # Displays actual employee username on terminal header
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
        modifiers=modifiers_list,
        store_info=store_info
    )

@pos_bp.route('/portal/<username>/pos/checkout', methods=['POST'])
def process_pos_checkout(username):
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
    
    # Correctly attributes sales & drawer entries to specific employee
    operator = session.get('staff_username') or session.get('logged_in_user', username)

    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Recipes'")
        has_recipes = cursor.fetchone() is not None

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifier_Recipes'")
        has_mod_recipes = cursor.fetchone() is not None

        recipe_map = {}
        if has_recipes:
            cursor.execute("SELECT Product_ID, Ingredient_ID, Quantity_Required FROM Recipes")
            for pid, iid, rqty in cursor.fetchall():
                recipe_map.setdefault(str(pid), []).append((str(iid), float(rqty or 0.0)))

        mod_recipe_map = {}
        if has_mod_recipes:
            cursor.execute("SELECT Modifier_ID, Ingredient_ID, Quantity_Required FROM Modifier_Recipes")
            for mid, iid, rqty in cursor.fetchall():
                mod_recipe_map.setdefault(str(mid), []).append((str(iid), float(rqty or 0.0)))

        cursor.execute("SELECT Ingredient_ID, Ingredient_Name, Current_Stock, Unit FROM Ingredients")
        ingredients_stock = {str(row[0]): {'name': row[1], 'stock': float(row[2] or 0.0), 'unit': row[3]} for row in cursor.fetchall()}

        line_counter = 1
        for item in items:
            p_id = str(item.get('product_id', ''))
            p_name = str(item.get('name', 'Product'))
            qty = float(item.get('qty', 1.0) or 1.0)
            unit_price = float(item.get('price', 0.0) or 0.0)
            line_total = qty * unit_price

            sale_line_id = f"{txn_id}-P{line_counter:02d}"
            line_counter += 1

            cursor.execute("""
                INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Live POS Order', ?)
            """, (sale_line_id, sale_date, sale_time, p_id, p_name, qty, unit_price, line_total, operator))

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

            for mod in item.get('modifiers', []):
                m_id = str(mod.get('id', ''))
                m_name = str(mod.get('name', 'Modifier'))
                m_qty = float(mod.get('qty', 1.0) or 1.0) * qty
                m_price = float(mod.get('price', 0.0) or 0.0)
                m_total = m_qty * m_price

                mod_line_id = f"{txn_id}-M{line_counter:02d}"
                line_counter += 1

                cursor.execute("""
                    INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Live POS Modifier', ?)
                """, (mod_line_id, sale_date, sale_time, m_id, f"Modifier: {m_name}", m_qty, m_price, m_total, operator))

                if m_id in mod_recipe_map:
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
                                f"POS Modifier: {m_qty:g}x {m_name} ({txn_id})"
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