# routes/sales.py - EOD Bulk Entry Blueprint
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd
import sqlite3
from datetime import datetime

sales_bp = Blueprint('sales', __name__)

@sales_bp.route('/portal/<username>/sales', methods=['GET', 'POST'])
def web_sales_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    db_path = f"data/client_{username}.db"
    client_db = InventoryDB(db_path)
    feedback_msg = None
    alert_type = "success"
    
    # Process End-of-Day Bulk Sheet Post Form Submission
    if request.method == 'POST':
        product_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        
        modifier_ids = request.form.getlist('modifier_id[]')
        modifier_quantities = request.form.getlist('modifier_quantity[]')
        
        chosen_date = request.form.get('sale_date', datetime.now().strftime("%Y-%m-%d")).strip()
        audit_note = request.form.get('audit_note', '').strip()
        
        # ===== BACKEND SECURITY ENFORCEMENT =====
        today_str = datetime.now().strftime("%Y-%m-%d")
        staff_role = session.get('staff_role', 'Staff')
        is_backdated = (chosen_date != today_str)
        
        if is_backdated and staff_role not in ['Platform Owner Admin', 'Store Manager']:
            return redirect(f"/portal/{username}/sales?error=Security Block: Only Managers and Admins are authorized to submit backdated ledger entries.")
            
        if is_backdated and not audit_note:
            return redirect(f"/portal/{username}/sales?error=Security Policy Violation: Audit entry notes are strictly mandatory for backdated adjustments.")
            
        for qty_str in quantities + modifier_quantities:
            if qty_str and float(qty_str) < 0:
                return redirect(f"/portal/{username}/sales?error=Security Block: Negative quantities are not allowed on the standard EOD sheet. Voids must be processed through the Corrections module.")
        # =========================================
        
        processed_count = 0
        blocked_items = []
        products_df = client_db.get_all_products()
        modifiers_df = client_db.read_tab('Modifiers')
        
        try:
            conn = sqlite3.connect(db_path, timeout=20.0)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(Sales);")
            sales_cols = [row[1] for row in cursor.fetchall()]
            if 'Unit_Cost' not in sales_cols:
                cursor.execute("ALTER TABLE Sales ADD COLUMN Unit_Cost REAL DEFAULT 0.0;")
            if 'Entry_Reason' not in sales_cols:
                cursor.execute("ALTER TABLE Sales ADD COLUMN Entry_Reason TEXT DEFAULT '';")
            if 'System_Timestamp' not in sales_cols:
                cursor.execute("ALTER TABLE Sales ADD COLUMN System_Timestamp TEXT DEFAULT '';")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Schema check error: {e}")

        # 1. Process Product Sales
        for p_id, qty_str in zip(product_ids, quantities):
            if not qty_str or float(qty_str or 0) == 0:
                continue
                
            qty = float(qty_str)
            p_name = p_id
            unit_price = 0.0
            unit_cost = 0.0
            
            if not products_df.empty:
                prod_row = products_df[products_df['Product_ID'] == p_id]
                if not prod_row.empty:
                    p_name = prod_row['Product_Name'].values[0]
                    unit_price = float(prod_row['Selling_Price'].values[0] or 0.0)
                    if 'Cost_Price' in prod_row.columns:
                        try:
                            unit_cost = float(prod_row['Cost_Price'].values[0] or 0.0)
                        except (ValueError, TypeError):
                            unit_cost = 0.0
                
            stock_ok, stock_msg = client_db.update_inventory_from_sale(p_id, qty)
            if stock_ok:
                try:
                    conn = sqlite3.connect(db_path, timeout=20.0)
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM Sales")
                    sale_count = cursor.fetchone()[0]
                    sale_id = f"SALE{sale_count + 1:04d}"
                    total_amt = qty * unit_price
                    sale_time = datetime.now().strftime("%H:%M:%S")
                    system_time_exact = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    cursor.execute("""
                        INSERT INTO Sales (Sale_ID, Product_ID, Quantity, Sale_Date, Sale_Time, Total_Amount, Unit_Cost, Entry_Reason, System_Timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (sale_id, p_id, qty, chosen_date, sale_time, total_amt, unit_cost, audit_note, system_time_exact))
                    conn.commit()
                    conn.close()
                    processed_count += 1
                except Exception as e:
                    blocked_items.append(f"{p_name} (Database Error: {str(e)})")
            else:
                blocked_items.append(f"{p_name} ({stock_msg.strip()})")

        # 2. Process Modifier Add-On Sales
        for m_id, m_qty_str in zip(modifier_ids, modifier_quantities):
            if not m_qty_str or float(m_qty_str or 0) == 0:
                continue

            m_qty = float(m_qty_str)
            m_name = m_id
            m_price = 0.0

            if not modifiers_df.empty:
                mod_row = modifiers_df[modifiers_df['Modifier_ID'] == m_id]
                if not mod_row.empty:
                    m_name = mod_row['Modifier_Name'].values[0]
                    m_price = float(mod_row['Price'].values[0] or 0.0)

            mod_stock_ok, mod_stock_msg = client_db.update_inventory_from_modifier_sale(m_id, m_qty, username=username)
            if mod_stock_ok:
                try:
                    conn = sqlite3.connect(db_path, timeout=20.0)
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM Sales")
                    sale_count = cursor.fetchone()[0]
                    sale_id = f"SALE{sale_count + 1:04d}"
                    total_amt = m_qty * m_price
                    sale_time = datetime.now().strftime("%H:%M:%S")
                    system_time_exact = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    cursor.execute("""
                        INSERT INTO Sales (Sale_ID, Product_ID, Quantity, Sale_Date, Sale_Time, Total_Amount, Unit_Cost, Entry_Reason, System_Timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (sale_id, f"MOD:{m_id}", m_qty, chosen_date, sale_time, total_amt, 0.0, f"Modifier: {m_name} | {audit_note}".strip(), system_time_exact))
                    conn.commit()
                    conn.close()
                    processed_count += 1
                except Exception as e:
                    blocked_items.append(f"{m_name} Add-On (Database Error: {str(e)})")
            else:
                blocked_items.append(f"{m_name} Add-On ({mod_stock_msg.strip()})")

        if processed_count > 0 and not blocked_items:
            feedback_msg = f"EOD Sync Complete! Successfully logged operations for {processed_count} items/modifiers on accounting date: {chosen_date}."
            alert_type = "success"
        elif processed_count > 0 and blocked_items:
            feedback_msg = f"Partial Sync: Processed {processed_count} updates for {chosen_date}. Some entries skipped:\n" + " | ".join(blocked_items)
            alert_type = "warning"
        elif len(blocked_items) > 0:
            feedback_msg = "EOD Sync Failed! Insufficient ingredients stock metrics:\n" + " | ".join(blocked_items)
            alert_type = "danger"
        else:
            feedback_msg = "No sales numbers were entered. Ledger entries remain unchanged."
            alert_type = "info"

    # ===== GET METHOD =====
    sales_df = client_db.read_tab('Sales')
    master_products_df = client_db.get_all_products()
    modifiers_df = client_db.read_tab('Modifiers')
    
    search = request.args.get('search', '').lower().strip()
    category = request.args.get('category', 'All')
    sort_by = request.args.get('sort_by', 'name')
    order = request.args.get('order', 'asc')

    categories = []
    grouped_products = {}
    active_modifiers = []

    if not modifiers_df.empty:
        if 'Active' in modifiers_df.columns:
            active_mods_df = modifiers_df[modifiers_df['Active'].astype(str).str.upper() == 'YES']
        else:
            active_mods_df = modifiers_df
        active_modifiers = active_mods_df.to_dict('records')
    
    filtered_products_df = master_products_df.copy() if not master_products_df.empty else pd.DataFrame()
    
    if not master_products_df.empty:
        if 'Category' in master_products_df.columns:
            categories = sorted([c for c in master_products_df['Category'].dropna().unique() if c])
            
        if search:
            filtered_products_df = filtered_products_df[
                filtered_products_df['Product_Name'].str.lower().str.contains(search) | 
                filtered_products_df['Product_ID'].str.lower().str.contains(search) |
                (filtered_products_df['Parent_Item'].fillna('').str.lower().str.contains(search) if 'Parent_Item' in filtered_products_df.columns else False)
            ]
        if category != 'All':
            filtered_products_df = filtered_products_df[filtered_products_df['Category'] == category]
            
        ascending = (order == 'asc')
        if sort_by == 'name':
            filtered_products_df = filtered_products_df.sort_values('Product_Name', ascending=ascending)
        elif sort_by == 'price':
            filtered_products_df = filtered_products_df.sort_values('Selling_Price', ascending=ascending)

        if 'Parent_Item' not in filtered_products_df.columns:
            filtered_products_df['Parent_Item'] = filtered_products_df['Product_Name']
        if 'Variant_Name' not in filtered_products_df.columns:
            filtered_products_df['Variant_Name'] = 'Regular'

        for _, row in filtered_products_df.iterrows():
            p_dict = row.to_dict()
            parent_name = str(p_dict.get('Parent_Item') or p_dict.get('Product_Name') or 'Uncategorized').strip()
            if not parent_name:
                parent_name = str(p_dict.get('Product_Name', 'Unknown Product')).strip()
            
            if parent_name not in grouped_products:
                grouped_products[parent_name] = []
            grouped_products[parent_name].append(p_dict)

    grouped_history_list = []
    if not sales_df.empty:
        sales_df = sales_df.sort_values('Sale_ID', ascending=False)
        unique_dates = sorted(list(sales_df['Sale_Date'].dropna().unique()), reverse=True)
        
        for date_val in unique_dates:
            date_df = sales_df[sales_df['Sale_Date'] == date_val]
            day_entries = []
            day_total_qty = 0.0
            day_total_revenue = 0.0
            
            for _, row in date_df.iterrows():
                p_id = str(row['Product_ID'])
                p_name = p_id
                
                if p_id.startswith('MOD:'):
                    mod_code = p_id.replace('MOD:', '')
                    if not modifiers_df.empty:
                        m_match = modifiers_df[modifiers_df['Modifier_ID'] == mod_code]
                        if not m_match.empty:
                            p_name = f"[Add-On] {m_match['Modifier_Name'].values[0]}"
                elif not master_products_df.empty:
                    match = master_products_df[master_products_df['Product_ID'] == p_id]
                    if not match.empty: 
                        p_name = match['Product_Name'].values[0]
                
                qty = float(row['Quantity'] or 0)
                revenue = float(row['Total_Amount'] or 0)
                
                day_total_qty += qty
                day_total_revenue += revenue
                
                day_entries.append({
                    'Sale_ID': row['Sale_ID'],
                    'Product_Name': p_name,
                    'Quantity': qty,
                    'Sale_Time': row['Sale_Time'] if 'Sale_Time' in sales_df.columns else '',
                    'Total_Amount': revenue,
                    'Reason': row.get('Entry_Reason', '') if 'Entry_Reason' in sales_df.columns else ''
                })
            
            grouped_history_list.append({
                'date': date_val,
                'total_qty': day_total_qty,
                'total_revenue': day_total_revenue,
                'entries': day_entries
            })

    server_error = request.args.get('error', '')
    if server_error:
        feedback_msg = server_error
        alert_type = "danger"

    return render_template(
        'sales.html',
        username=username,
        grouped_products=grouped_products,
        active_modifiers=active_modifiers,
        categories=categories,
        sales_history=grouped_history_list,
        msg=feedback_msg,
        alert_type=alert_type,
        current_search=search,
        current_category=category,
        current_sort=sort_by,
        current_order=order
    )