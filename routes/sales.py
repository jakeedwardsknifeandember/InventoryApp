# routes/sales.py - End-of-Day (EOD) Sales Entry, Shift Starting Float Sync & Multi-Channel Tender Balancing Engine
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import sqlite3
import pandas as pd
import numpy as np
import re
from datetime import datetime
from collections import defaultdict

sales_bp = Blueprint('sales', __name__)

def resolve_parent_and_variant(p):
    """
    Intelligently extracts the master parent drink family and variant label.
    Supports explicit database fields as well as standard beverage naming patterns.
    """
    raw_parent = p.get('Parent_Item')
    raw_variant = p.get('Variant_Name')
    
    if raw_parent and str(raw_parent).strip().lower() not in ['nan', 'none', '', 'null']:
        parent = str(raw_parent).strip()
        variant = str(raw_variant).strip() if (raw_variant and str(raw_variant).strip().lower() not in ['nan', 'none', '', 'null']) else 'Regular'
        return parent, variant

    full_name = str(p.get('Product_Name') or '').strip()
    
    prefix_match = re.match(r"^(Hot|Iced|Cold|Warm)\s*[-–—:]?\s*(.+)$", full_name, re.IGNORECASE)
    if prefix_match:
        variant = prefix_match.group(1).strip().capitalize()
        parent = prefix_match.group(2).strip()
        return parent, variant

    suffix_match = re.match(r"^(.+?)\s*[-–—:(]\s*(Hot|Iced|Cold|Warm|12oz|16oz|22oz|Regular|Large)\)?$", full_name, re.IGNORECASE)
    if suffix_match:
        parent = suffix_match.group(1).strip()
        variant = suffix_match.group(2).strip().capitalize()
        return parent, variant

    delimiter_match = re.match(r"^([^-–—(]+)\s*[-–—]\s*(.+)$", full_name)
    if delimiter_match:
        part1 = delimiter_match.group(1).strip()
        part2 = delimiter_match.group(2).strip()
        if part1.lower() in ['hot', 'iced', 'cold', 'warm']:
            return part2, part1.capitalize()
        return part1, part2

    return full_name, "Regular"

def ensure_sales_database_schema(conn):
    """
    Auto-migrates Sales, Shift_Logs, Inventory_Audit_Log, Sales_Discounts, and Cash_Drawer_Logs tables.
    Safely adds missing columns without data loss.
    """
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Shift_Logs (
            Shift_ID TEXT PRIMARY KEY,
            Cashier_Open TEXT,
            Cashier_Close TEXT,
            Date TEXT,
            Time_Opened TEXT,
            Time_Closed TEXT,
            Starting_Float REAL DEFAULT 0.0,
            Cash_Sales REAL DEFAULT 0.0,
            Cash_Paid_Outs REAL DEFAULT 0.0,
            Expected_Cash REAL DEFAULT 0.0,
            Actual_Counted_Cash REAL DEFAULT 0.0,
            Discrepancy_Over_Short REAL DEFAULT 0.0,
            Total_Net_Sales REAL DEFAULT 0.0,
            Total_Transactions INTEGER DEFAULT 0,
            Status TEXT DEFAULT 'OPEN',
            Notes TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(Shift_Logs)")
    existing_shift_cols = {row[1] for row in cursor.fetchall()}
    needed_shift_cols = {
        'Cashier_Close': 'TEXT',
        'Date': 'TEXT',
        'Time_Opened': 'TEXT',
        'Time_Closed': 'TEXT',
        'Starting_Float': 'REAL DEFAULT 0.0',
        'Cash_Sales': 'REAL DEFAULT 0.0',
        'Cash_Paid_Outs': 'REAL DEFAULT 0.0',
        'Expected_Cash': 'REAL DEFAULT 0.0',
        'Actual_Counted_Cash': 'REAL DEFAULT 0.0',
        'Discrepancy_Over_Short': 'REAL DEFAULT 0.0',
        'Total_Net_Sales': 'REAL DEFAULT 0.0',
        'Total_Transactions': 'INTEGER DEFAULT 0',
        'Status': "TEXT DEFAULT 'OPEN'",
        'Notes': 'TEXT'
    }
    for col_name, col_type in needed_shift_cols.items():
        if col_name not in existing_shift_cols:
            cursor.execute(f"ALTER TABLE Shift_Logs ADD COLUMN {col_name} {col_type}")

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
    cursor.execute("PRAGMA table_info(Sales)")
    existing_sales_cols = {row[1] for row in cursor.fetchall()}
    needed_sales_cols = {
        'Sale_Date': 'TEXT',
        'Sale_Time': 'TEXT',
        'Product_ID': 'TEXT',
        'Product_Name': 'TEXT',
        'Quantity': 'REAL',
        'Price': 'REAL',
        'Total_Amount': 'REAL',
        'Reason': 'TEXT',
        'Recorded_By': 'TEXT'
    }
    for col_name, col_type in needed_sales_cols.items():
        if col_name not in existing_sales_cols:
            cursor.execute(f"ALTER TABLE Sales ADD COLUMN {col_name} {col_type}")

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
    cursor.execute("PRAGMA table_info(Inventory_Audit_Log)")
    existing_audit_cols = {row[1] for row in cursor.fetchall()}
    needed_audit_cols = {
        'Audit_ID': 'TEXT',
        'Date': 'TEXT',
        'Ingredient_Name': 'TEXT',
        'Theoretical': 'REAL',
        'Physical': 'REAL',
        'Variance': 'REAL',
        'Notes': 'TEXT'
    }
    for col_name, col_type in needed_audit_cols.items():
        if col_name not in existing_audit_cols:
            cursor.execute(f"ALTER TABLE Inventory_Audit_Log ADD COLUMN {col_name} {col_type}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Sales_Discounts (
            Discount_Tx_ID TEXT PRIMARY KEY,
            Batch_ID TEXT,
            Sale_Date TEXT,
            Sale_Time TEXT,
            Discount_ID TEXT,
            Discount_Name TEXT,
            Category TEXT,
            Amount REAL,
            Notes TEXT,
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
    cursor.execute("PRAGMA table_info(Cash_Drawer_Logs)")
    existing_drawer_cols = {row[1] for row in cursor.fetchall()}
    needed_drawer_cols = {
        'Batch_ID': 'TEXT',
        'Date': 'TEXT',
        'Time': 'TEXT',
        'Starting_Float': 'REAL DEFAULT 0.0',
        'Cash_Sales': 'REAL DEFAULT 0.0',
        'Cash_Paid_Outs': 'REAL DEFAULT 0.0',
        'Expected_Cash': 'REAL DEFAULT 0.0',
        'Actual_Counted_Cash': 'REAL DEFAULT 0.0',
        'Discrepancy_Over_Short': 'REAL DEFAULT 0.0',
        'GCash_Sales': 'REAL DEFAULT 0.0',
        'Maya_Sales': 'REAL DEFAULT 0.0',
        'Card_Sales': 'REAL DEFAULT 0.0',
        'Grab_Gross': 'REAL DEFAULT 0.0',
        'Grab_Commission': 'REAL DEFAULT 0.0',
        'Grab_Net': 'REAL DEFAULT 0.0',
        'Foodpanda_Gross': 'REAL DEFAULT 0.0',
        'Foodpanda_Commission': 'REAL DEFAULT 0.0',
        'Foodpanda_Net': 'REAL DEFAULT 0.0',
        'Total_Settled_Tenders': 'REAL DEFAULT 0.0',
        'Tender_Variance': 'REAL DEFAULT 0.0',
        'Explanation_Notes': 'TEXT',
        'Recorded_By': 'TEXT'
    }
    for col_name, col_type in needed_drawer_cols.items():
        if col_name not in existing_drawer_cols:
            cursor.execute(f"ALTER TABLE Cash_Drawer_Logs ADD COLUMN {col_name} {col_type}")

    conn.commit()

@sales_bp.route('/portal/<username>/sales', methods=['GET', 'POST'])
def web_sales_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username:
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    feedback_msg = None
    alert_type = "success"

    conn = sqlite3.connect(client_db_path, timeout=20.0)
    ensure_sales_database_schema(conn)
    conn.close()

    # =================================================================
    # 1. POST METHOD: SUBMIT CONSOLIDATED EOD SALES & MULTI-TENDER SETTLEMENT
    # =================================================================
    if request.method == 'POST':
        sale_date = request.form.get('sale_date', '').strip() or datetime.now().strftime("%Y-%m-%d")
        audit_note = request.form.get('audit_note', '').strip()
        recorded_by = session.get('staff_role') or session.get('logged_in_user') or 'Staff'
        
        prod_ids = request.form.getlist('product_id[]')
        prod_qtys = request.form.getlist('quantity[]')
        
        mod_ids = request.form.getlist('modifier_id[]')
        mod_qtys = request.form.getlist('modifier_quantity[]')

        disc_ids = request.form.getlist('discount_id[]')
        disc_amts = request.form.getlist('discount_amount[]')
        disc_notes = request.form.getlist('discount_notes[]')

        starting_float_str = request.form.get('starting_float', '0').strip()
        cash_sales_str = request.form.get('cash_sales', '0').strip()
        cash_paid_outs_str = request.form.get('cash_paid_outs', '0').strip()
        cash_paid_outs_reason = request.form.get('cash_paid_outs_reason', '').strip()
        actual_counted_cash_str = request.form.get('actual_counted_cash', '0').strip()
        drawer_notes = request.form.get('drawer_notes', '').strip()

        gcash_sales_str = request.form.get('gcash_sales', '0').strip()
        maya_sales_str = request.form.get('maya_sales', '0').strip()
        card_sales_str = request.form.get('card_sales', '0').strip()

        grab_gross_str = request.form.get('grab_gross', '0').strip()
        grab_comm_str = request.form.get('grab_comm', '0').strip()
        foodpanda_gross_str = request.form.get('foodpanda_gross', '0').strip()
        foodpanda_comm_str = request.form.get('foodpanda_comm', '0').strip()

        def parse_float_safe(val_str):
            try:
                return float(val_str or 0.0)
            except (ValueError, TypeError):
                return 0.0

        starting_float = parse_float_safe(starting_float_str)
        cash_sales = parse_float_safe(cash_sales_str)
        cash_paid_outs = parse_float_safe(cash_paid_outs_str)
        actual_counted_cash = parse_float_safe(actual_counted_cash_str)

        gcash_sales = parse_float_safe(gcash_sales_str)
        maya_sales = parse_float_safe(maya_sales_str)
        card_sales = parse_float_safe(card_sales_str)

        grab_gross = parse_float_safe(grab_gross_str)
        grab_comm = parse_float_safe(grab_comm_str)
        grab_net = max(0.0, grab_gross - grab_comm)

        foodpanda_gross = parse_float_safe(foodpanda_gross_str)
        foodpanda_comm = parse_float_safe(foodpanda_comm_str)
        foodpanda_net = max(0.0, foodpanda_gross - foodpanda_comm)

        expected_cash = starting_float + cash_sales - cash_paid_outs
        has_drawer_entry = (actual_counted_cash > 0 or cash_sales > 0 or starting_float > 0 or cash_paid_outs > 0)
        over_short = (actual_counted_cash - expected_cash) if has_drawer_entry else 0.0
        total_settled_tenders = cash_sales + gcash_sales + maya_sales + card_sales + grab_net + foodpanda_net
        
        conn = sqlite3.connect(client_db_path, timeout=20.0)
        cursor = conn.cursor()

        date_slug = sale_date.replace('-', '')
        time_slug = datetime.now().strftime("%H%M%S")
        batch_id = f"EOD{date_slug}_{time_slug}"
        sale_time_str = datetime.now().strftime("%H:%M:%S")

        total_required_ingredients = defaultdict(float)
        sold_summary_list = []
        valid_sales_payload = []
        valid_modifiers_payload = []
        valid_discounts_payload = []

        # Process Product Requirements
        for p_id, q_str in zip(prod_ids, prod_qtys):
            p_qty = parse_float_safe(q_str)
            if p_qty == 0:
                continue

            cursor.execute("SELECT Product_Name, Selling_Price FROM Products WHERE Product_ID = ?", (p_id,))
            prod_match = cursor.fetchone()
            p_name = prod_match[0] if prod_match else p_id
            p_price = float(prod_match[1] or 0.0) if prod_match else 0.0
            
            valid_sales_payload.append({
                'id': p_id, 'name': p_name, 'qty': p_qty, 'price': p_price, 'total': p_qty * p_price
            })
            sold_summary_list.append(f"{p_qty:g}x {p_name}")

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Recipes'")
            if cursor.fetchone():
                cursor.execute("SELECT Ingredient_ID, Quantity_Required FROM Recipes WHERE Product_ID = ?", (p_id,))
                for ing_id, req_qty in cursor.fetchall():
                    total_required_ingredients[str(ing_id)] += float(req_qty or 0.0) * p_qty

        # Process Modifier Requirements
        for m_id, mq_str in zip(mod_ids, mod_qtys):
            m_qty = parse_float_safe(mq_str)
            if m_qty == 0:
                continue

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifiers'")
            m_name = m_id
            m_price = 0.0
            if cursor.fetchone():
                cursor.execute("SELECT Modifier_Name, Price FROM Modifiers WHERE Modifier_ID = ?", (m_id,))
                mod_match = cursor.fetchone()
                if mod_match:
                    m_name = mod_match[0] or m_id
                    m_price = float(mod_match[1] or 0.0)

            valid_modifiers_payload.append({
                'id': m_id, 'name': m_name, 'qty': m_qty, 'price': m_price, 'total': m_qty * m_price
            })
            sold_summary_list.append(f"{m_qty:g}x {m_name}")

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifier_Recipes'")
            if cursor.fetchone():
                cursor.execute("SELECT Ingredient_ID, Quantity_Required FROM Modifier_Recipes WHERE Modifier_ID = ?", (m_id,))
                for ing_id, req_qty in cursor.fetchall():
                    total_required_ingredients[str(ing_id)] += float(req_qty or 0.0) * m_qty

        # Process Discounts
        discounts_total_amount = 0.0
        for d_id, d_amt_str, d_note in zip(disc_ids, disc_amts, disc_notes):
            d_amt = parse_float_safe(d_amt_str)
            if d_amt <= 0:
                continue

            d_name = d_id
            d_cat = "Promotional / Marketing"
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Discounts'")
            if cursor.fetchone():
                cursor.execute("SELECT Discount_Name, Category FROM Discounts WHERE Discount_ID = ?", (d_id,))
                disc_match = cursor.fetchone()
                if disc_match:
                    d_name = disc_match[0] or d_id
                    d_cat = disc_match[1] or "Promotional / Marketing"

            valid_discounts_payload.append({
                'id': d_id, 'name': d_name, 'category': d_cat, 'amount': d_amt, 'notes': (d_note or '').strip()
            })
            discounts_total_amount += d_amt

        cursor.execute("SELECT COUNT(*) FROM Sales WHERE Sale_Date = ?", (sale_date,))
        existing_sales_count_today = cursor.fetchone()[0]

        if not valid_sales_payload and not valid_modifiers_payload and not has_drawer_entry and existing_sales_count_today == 0:
            conn.close()
            return redirect(f"/portal/{username}/sales?target_date={sale_date}&msg=Input Notice: No activity or drawer counts were entered.&alert_type=warning")

        # Check Stock Sufficiency for Manual Items
        insufficient_ingredients = []
        for ing_id, needed_qty in total_required_ingredients.items():
            if needed_qty <= 0:
                continue
            cursor.execute("SELECT Ingredient_Name, Current_Stock, Unit FROM Ingredients WHERE Ingredient_ID = ?", (ing_id,))
            ing_row = cursor.fetchone()
            if ing_row:
                ing_name = ing_row[0] or ing_id
                current_stock = float(ing_row[1] or 0.0)
                unit_label = ing_row[2] or 'units'
                if current_stock < needed_qty:
                    insufficient_ingredients.append({
                        'name': ing_name,
                        'available': current_stock,
                        'needed': needed_qty,
                        'unit': unit_label
                    })

        if insufficient_ingredients:
            conn.close()
            error_details = []
            for item in insufficient_ingredients[:3]:
                error_details.append(f"{item['name']} (Stock: {item['available']:g} {item['unit']}, Needs: {item['needed']:g} {item['unit']})")
            if len(insufficient_ingredients) > 3:
                error_details.append(f"and {len(insufficient_ingredients) - 3} more items")
            err_msg = f"Inventory Depletion Block: Insufficient stock for: {'; '.join(error_details)}."
            return redirect(f"/portal/{username}/sales?target_date={sale_date}&msg={err_msg}&alert_type=danger")

        # Commit Sales
        for idx, item in enumerate(valid_sales_payload, start=1):
            sale_line_id = f"{batch_id}-P{idx:02d}"
            cursor.execute("""
                INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sale_line_id, sale_date, sale_time_str, item['id'], item['name'], item['qty'], item['price'], item['total'], audit_note or f"Manual EOD Entry {batch_id}", recorded_by))

        for idx, item in enumerate(valid_modifiers_payload, start=1):
            mod_line_id = f"{batch_id}-M{idx:02d}"
            cursor.execute("""
                INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (mod_line_id, sale_date, sale_time_str, item['id'], f"Modifier: {item['name']}", item['qty'], item['price'], item['total'], audit_note or f"Manual EOD Entry {batch_id}", recorded_by))

        for idx, disc in enumerate(valid_discounts_payload, start=1):
            disc_line_id = f"{batch_id}-D{idx:02d}"
            cursor.execute("""
                INSERT INTO Sales_Discounts (Discount_Tx_ID, Batch_ID, Sale_Date, Sale_Time, Discount_ID, Discount_Name, Category, Amount, Notes, Recorded_By)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (disc_line_id, batch_id, sale_date, sale_time_str, disc['id'], disc['name'], disc['category'], disc['amount'], disc['notes'], recorded_by))

            cursor.execute("""
                INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """, (disc_line_id, sale_date, sale_time_str, disc['id'], f"Discount: {disc['name']}", -disc['amount'], -disc['amount'], f"[{disc['category']}] {disc['notes']}", recorded_by))

        cursor.execute("SELECT COALESCE(SUM(Total_Amount), 0.0) FROM Sales WHERE Sale_Date = ?", (sale_date,))
        net_sales_day_total = float(cursor.fetchone()[0] or 0.0)
        tender_variance = total_settled_tenders - net_sales_day_total

        drawer_tx_id = f"{batch_id}-TNDR"
        full_drawer_notes = f"{drawer_notes} | Paid-Out Note: {cash_paid_outs_reason}".strip(" | ")

        cursor.execute("""
            INSERT INTO Cash_Drawer_Logs (
                Drawer_Tx_ID, Batch_ID, Date, Time, Starting_Float, Cash_Sales,
                Cash_Paid_Outs, Expected_Cash, Actual_Counted_Cash, Discrepancy_Over_Short,
                GCash_Sales, Maya_Sales, Card_Sales, Grab_Gross, Grab_Commission, Grab_Net,
                Foodpanda_Gross, Foodpanda_Commission, Foodpanda_Net, Total_Settled_Tenders,
                Tender_Variance, Explanation_Notes, Recorded_By
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            drawer_tx_id, batch_id, sale_date, sale_time_str, starting_float, cash_sales,
            cash_paid_outs, expected_cash, actual_counted_cash, over_short,
            gcash_sales, maya_sales, card_sales, grab_gross, grab_comm, grab_net,
            foodpanda_gross, foodpanda_comm, foodpanda_net, total_settled_tenders,
            tender_variance, full_drawer_notes, recorded_by
        ))

        # CLOSE REGISTER SHIFT IN SHIFT_LOGS ON EOD COMMIT
        cursor.execute("""
            UPDATE Shift_Logs 
            SET Cashier_Close = ?, Time_Closed = ?, Expected_Cash = ?, Actual_Counted_Cash = ?,
                Discrepancy_Over_Short = ?, Status = 'CLOSED', Notes = COALESCE(Notes || ' | ', '') || 'Closed via EOD Sales Worksheet'
            WHERE Date = ? AND Status = 'OPEN'
        """, (recorded_by, sale_time_str, expected_cash, actual_counted_cash, over_short, sale_date))

        # Deduct Ingredients
        for ing_id, tot_deduct in total_required_ingredients.items():
            if tot_deduct <= 0:
                continue
            cursor.execute("SELECT Current_Stock, Ingredient_Name FROM Ingredients WHERE Ingredient_ID = ?", (ing_id,))
            ing_match = cursor.fetchone()
            if ing_match:
                cur_stock, ing_name = ing_match
                new_stock = float(cur_stock or 0.0) - tot_deduct
                cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_stock, ing_id))
                cursor.execute("""
                    INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (batch_id, sale_date, ing_name, cur_stock, new_stock, -tot_deduct, f"Manual EOD Depletion: {batch_id}"))

        conn.commit()
        conn.close()
        client_db.update_all_product_costs()

        feedback_msg = f"Shift Closeout Saved: Reconciled tenders for {sale_date}. Settled: ₱{total_settled_tenders:,.2f} (Over/Short: ₱{over_short:+,.2f})."
        return redirect(f"/portal/{username}/sales?target_date={sale_date}&msg={feedback_msg}&alert_type=success")

    # =================================================================
    # 2. GET METHOD: RENDER GROUPED WORKSHEET & SHIFT HOOKS
    # =================================================================
    target_date = request.args.get('target_date', datetime.now().strftime("%Y-%m-%d")).strip()
    conn = sqlite3.connect(client_db_path, timeout=20.0)
    cursor = conn.cursor()

    products_df = pd.read_sql("SELECT * FROM Products WHERE Active = 'Yes' OR Active = 'yes'", conn)
    grouped_products = defaultdict(list)
    categories = []
    if not products_df.empty:
        categories = sorted(list(set(str(c).strip() for c in products_df['Category'].dropna() if str(c).strip())))
        for _, p in products_df.iterrows():
            parent_name, variant_name = resolve_parent_and_variant(p)
            grouped_products[parent_name].append({
                'Product_ID': str(p['Product_ID']),
                'Product_Name': str(p['Product_Name']),
                'Parent_Item': parent_name,
                'Variant_Name': variant_name,
                'Category': str(p.get('Category') or 'General'),
                'Selling_Price': float(pd.to_numeric(p.get('Selling_Price', 0.0), errors='coerce') or 0.0)
            })

    active_modifiers = []
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifiers'")
    if cursor.fetchone():
        mods_df = pd.read_sql("SELECT * FROM Modifiers WHERE Active = 'Yes' OR Active = 'yes'", conn)
        if not mods_df.empty:
            active_modifiers = mods_df.to_dict('records')

    active_discounts = []
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Discounts'")
    if cursor.fetchone():
        cursor.execute("SELECT * FROM Discounts WHERE Active = 'Yes' OR Active = 'yes' ORDER BY Discount_ID ASC")
        rows = cursor.fetchall()
        cols = [c[0] for c in cursor.description]
        for r in rows:
            d_dict = dict(zip(cols, r))
            d_dict['Value'] = float(d_dict.get('Value') or 0.0)
            d_dict['Category'] = str(d_dict.get('Category') or 'Promotional / Marketing')
            active_discounts.append(d_dict)

    # 4. Live POS Products sold count (net of voids)
    cursor.execute("""
        SELECT Product_ID, SUM(Quantity)
        FROM Sales
        WHERE Sale_Date = ? 
          AND Product_ID NOT LIKE 'MOD%' 
          AND Product_ID NOT LIKE 'DISC%' 
          AND Product_ID != 'DISCOUNT'
          AND (Product_Name NOT LIKE 'Discount:%' AND Product_Name NOT LIKE 'Modifier:%')
        GROUP BY Product_ID
    """, (target_date,))
    pos_prod_qty = {str(r[0]): float(r[1] or 0.0) for r in cursor.fetchall()}

    cursor.execute("""
        SELECT Product_ID, SUM(Quantity)
        FROM Sales
        WHERE Sale_Date = ? 
          AND (Product_ID LIKE 'MOD%' OR Product_Name LIKE 'Modifier:%')
        GROUP BY Product_ID
    """, (target_date,))
    pos_mod_qty = {str(r[0]): float(r[1] or 0.0) for r in cursor.fetchall()}

    cursor.execute("""
        SELECT Product_Name, SUM(ABS(Total_Amount))
        FROM Sales
        WHERE Sale_Date = ? 
          AND (Product_ID = 'DISCOUNT' OR Product_ID LIKE 'DISC%' OR Product_Name LIKE 'Discount:%')
        GROUP BY Product_Name
    """, (target_date,))
    pos_discounts = {str(r[0]): float(r[1] or 0.0) for r in cursor.fetchall()}

    cursor.execute("""
        SELECT 
            COALESCE(SUM(Cash_Sales), 0.0),
            COALESCE(SUM(GCash_Sales), 0.0),
            COALESCE(SUM(Maya_Sales), 0.0),
            COALESCE(SUM(Card_Sales), 0.0)
        FROM Cash_Drawer_Logs
        WHERE Date = ? AND (Batch_ID LIKE 'POS%' OR Drawer_Tx_ID LIKE '%-TNDR')
    """, (target_date,))
    t_row = cursor.fetchone()
    pos_tenders = {
        'cash': float(t_row[0] or 0.0) if t_row else 0.0,
        'gcash': float(t_row[1] or 0.0) if t_row else 0.0,
        'maya': float(t_row[2] or 0.0) if t_row else 0.0,
        'card': float(t_row[3] or 0.0) if t_row else 0.0
    }

    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN Total_Amount > 0 THEN Total_Amount ELSE 0 END), 0.0),
            COALESCE(SUM(CASE WHEN Total_Amount < 0 THEN ABS(Total_Amount) ELSE 0 END), 0.0),
            COALESCE(SUM(Total_Amount), 0.0)
        FROM Sales
        WHERE Sale_Date = ?
    """, (target_date,))
    fin_row = cursor.fetchone()
    live_pos_summary = {
        'gross': float(fin_row[0] or 0.0) if fin_row else 0.0,
        'discounts': float(fin_row[1] or 0.0) if fin_row else 0.0,
        'net': float(fin_row[2] or 0.0) if fin_row else 0.0,
        'total_items': sum(pos_prod_qty.values()) + sum(pos_mod_qty.values())
    }

    # 5. QUERY ACTIVE OPEN SHIFT FIRST, FALLING BACK TO MOST RECENT SHIFT
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Shift_Logs'")
    pos_starting_float = 0.0
    active_shift_info = None
    if cursor.fetchone():
        shift_param = request.args.get('shift_id', '').strip()
        if shift_param:
            cursor.execute("""
                SELECT Shift_ID, Cashier_Open, Starting_Float, Cash_Sales, Total_Net_Sales, Status, Time_Opened
                FROM Shift_Logs
                WHERE Shift_ID = ?
                LIMIT 1
            """, (shift_param,))
        else:
            cursor.execute("""
                SELECT Shift_ID, Cashier_Open, Starting_Float, Cash_Sales, Total_Net_Sales, Status, Time_Opened
                FROM Shift_Logs
                WHERE Date = ?
                ORDER BY CASE WHEN Status = 'OPEN' THEN 0 ELSE 1 END, Shift_ID DESC
                LIMIT 1
            """, (target_date,))
        s_row = cursor.fetchone()
        if s_row:
            pos_starting_float = float(s_row[2] or 0.0)
            active_shift_info = {
                'shift_id': s_row[0],
                'cashier': s_row[1],
                'starting_float': pos_starting_float,
                'cash_sales': float(s_row[3] or 0.0),
                'net_sales': float(s_row[4] or 0.0),
                'status': s_row[5],
                'time': s_row[6]
            }
            if pos_tenders['cash'] == 0.0 and float(s_row[3] or 0.0) > 0.0:
                pos_tenders['cash'] = float(s_row[3] or 0.0)

    # 6. Store Settings
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Store_Settings'")
    store_settings = {}
    if cursor.fetchone():
        cursor.execute("SELECT Setting_Key, Setting_Value FROM Store_Settings")
        store_settings = dict(cursor.fetchall())
    store_settings.setdefault('enforce_blind_till', 'yes')
    store_settings.setdefault('master_admin_pin', '9999')

    # 7. Sales History
    sales_history = []
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Sales'")
    if cursor.fetchone():
        sales_ledger_df = pd.read_sql("SELECT * FROM Sales ORDER BY Sale_Date DESC, Sale_Time DESC", conn)
        drawer_df = pd.DataFrame()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Cash_Drawer_Logs'")
        if cursor.fetchone():
            drawer_df = pd.read_sql("SELECT * FROM Cash_Drawer_Logs ORDER BY Date DESC, Time DESC", conn)

        if not sales_ledger_df.empty:
            sales_ledger_df['Sale_Date'] = sales_ledger_df['Sale_Date'].astype(str)
            for u_date in sales_ledger_df['Sale_Date'].unique():
                day_entries = sales_ledger_df[sales_ledger_df['Sale_Date'] == u_date]
                prod_lines = day_entries[~day_entries['Product_Name'].str.startswith('Discount:')]
                t_qty = float(pd.to_numeric(prod_lines['Quantity'], errors='coerce').fillna(0.0).sum())
                g_rev = float(pd.to_numeric(day_entries[day_entries['Total_Amount'] > 0]['Total_Amount'], errors='coerce').fillna(0.0).sum())
                d_tot = abs(float(pd.to_numeric(day_entries[day_entries['Total_Amount'] < 0]['Total_Amount'], errors='coerce').fillna(0.0).sum()))
                n_rev = float(pd.to_numeric(day_entries['Total_Amount'], errors='coerce').fillna(0.0).sum())

                day_drawer = None
                if not drawer_df.empty and 'Date' in drawer_df.columns:
                    match_d = drawer_df[drawer_df['Date'] == u_date]
                    if not match_d.empty:
                        d_row = match_d.iloc[0]
                        day_drawer = {
                            'starting_float': float(d_row.get('Starting_Float') or 0.0),
                            'cash_sales': float(d_row.get('Cash_Sales') or 0.0),
                            'cash_paid_outs': float(d_row.get('Cash_Paid_Outs') or 0.0),
                            'expected_cash': float(d_row.get('Expected_Cash') or 0.0),
                            'actual_cash': float(d_row.get('Actual_Counted_Cash') or 0.0),
                            'over_short': float(d_row.get('Discrepancy_Over_Short') or 0.0),
                            'gcash': float(d_row.get('GCash_Sales') or 0.0),
                            'maya': float(d_row.get('Maya_Sales') or 0.0),
                            'card': float(d_row.get('Card_Sales') or 0.0),
                            'grab_gross': float(d_row.get('Grab_Gross') or 0.0),
                            'grab_comm': float(d_row.get('Grab_Commission') or 0.0),
                            'grab_net': float(d_row.get('Grab_Net') or 0.0),
                            'panda_gross': float(d_row.get('Foodpanda_Gross') or 0.0),
                            'panda_comm': float(d_row.get('Foodpanda_Commission') or 0.0),
                            'panda_net': float(d_row.get('Foodpanda_Net') or 0.0),
                            'total_tenders': float(d_row.get('Total_Settled_Tenders') or 0.0),
                            'variance': float(d_row.get('Tender_Variance') or 0.0),
                            'notes': str(d_row.get('Explanation_Notes') or '').strip()
                        }

                sales_history.append({
                    'date': u_date, 'total_qty': t_qty, 'total_revenue': n_rev, 'gross_revenue': g_rev,
                    'discount_total': d_tot, 'drawer': day_drawer, 'entries': day_entries.to_dict('records')
                })

    conn.close()

    return render_template(
        'sales.html',
        username=username,
        target_date=target_date,
        grouped_products=grouped_products,
        categories=categories,
        active_modifiers=active_modifiers,
        active_discounts=active_discounts,
        pos_prod_qty=pos_prod_qty,
        pos_mod_qty=pos_mod_qty,
        pos_discounts=pos_discounts,
        pos_tenders=pos_tenders,
        live_pos_summary=live_pos_summary,
        pos_starting_float=pos_starting_float,
        active_shift_info=active_shift_info,
        store_settings=store_settings,
        sales_history=sales_history,
        msg=request.args.get('msg', feedback_msg),
        alert_type=request.args.get('alert_type', alert_type)
    )