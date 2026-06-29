# routes/sales.py - EOD Bulk Entry Blueprint
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd
from datetime import datetime

sales_bp = Blueprint('sales', __name__)

@sales_bp.route('/portal/<username>/sales', methods=['GET', 'POST'])
def web_sales_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    client_db = InventoryDB(f"data/client_{username}.db")
    feedback_msg = None
    alert_type = "success"
    
    # Process End-of-Day Bulk Sheet Post Form Submission
    if request.method == 'POST':
        product_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        chosen_date = request.form.get('sale_date', datetime.now().strftime("%Y-%m-%d")).strip()
        audit_note = request.form.get('audit_note', '').strip()
        
        # ===== IRONCLAD BACKEND SECURITY ENFORCEMENT =====
        today_str = datetime.now().strftime("%Y-%m-%d")
        is_backdated = (chosen_date != today_str)
        
        has_negative = False
        for qty_str in quantities:
            if qty_str and float(qty_str) < 0:
                has_negative = True
                break
                
        if (is_backdated or has_negative) and not audit_note:
            return redirect(f"/portal/{username}/sales?error=Security Policy Violation: Audit entry notes are strictly mandatory for backdated adjustments or negative entries.")
        # =================================================
        
        processed_count = 0
        blocked_items = []
        products_df = client_db.get_all_products()
        
        for p_id, qty_str in zip(product_ids, quantities):
            if not qty_str or float(qty_str or 0) == 0:
                continue
                
            qty = float(qty_str)
            prod_row = products_df[products_df['Product_ID'] == p_id]
            
            if not prod_row.empty:
                p_name = prod_row['Product_Name'].values[0]
                unit_price = float(prod_row['Selling_Price'].values[0])
                
                # Triggers the inventory reduction script
                stock_ok, stock_msg = client_db.update_inventory_from_sale(p_id, qty)
                if stock_ok:
                    client_db.add_sale(p_id, qty, unit_price)
                    processed_count += 1
                else:
                    blocked_items.append(f"{p_name} ({stock_msg.strip()})")

        if processed_count > 0:
            sales_df = client_db.read_tab('Sales')
            if not sales_df.empty:
                if 'Entry_Reason' not in sales_df.columns:
                    sales_df['Entry_Reason'] = ""
                
                sales_df.iloc[-processed_count:, sales_df.columns.get_loc('Sale_Date')] = chosen_date
                if audit_note:
                    sales_df.iloc[-processed_count:, sales_df.columns.get_loc('Entry_Reason')] = audit_note
                
                client_db.save_tab('Sales', sales_df)

        if processed_count > 0 and not blocked_items:
            feedback_msg = f"📋 EOD Sync Complete! Successfully logged operations for {processed_count} items on accounting date: {chosen_date}."
            alert_type = "success"
        elif processed_count > 0 and blocked_items:
            feedback_msg = f"⚠️ Partial Sync: Processed {processed_count} updates for {chosen_date}. Some entries skipped due to ingredient shortages:\n" + " | ".join(blocked_items)
            alert_type = "warning"
        elif len(blocked_items) > 0:
            feedback_msg = "❌ EOD Sync Failed! Insufficient ingredients stock metrics:\n" + " | ".join(blocked_items)
            alert_type = "danger"
        else:
            feedback_msg = "ℹ️ No sales numbers were entered. Ledger entries remain unchanged."
            alert_type = "info"

    # ===== GET METHOD: DISPLAY DATA PROCESSING =====
    sales_df = client_db.read_tab('Sales')
    master_products_df = client_db.get_all_products()
    
    search = request.args.get('search', '').lower().strip()
    category = request.args.get('category', 'All')
    sort_by = request.args.get('sort_by', 'name')
    order = request.args.get('order', 'asc')

    categories = []
    active_products_list = []
    
    filtered_products_df = master_products_df.copy() if not master_products_df.empty else pd.DataFrame()
    
    if not master_products_df.empty:
        if 'Category' in master_products_df.columns:
            categories = sorted([c for c in master_products_df['Category'].dropna().unique() if c])
            
        if search:
            filtered_products_df = filtered_products_df[filtered_products_df['Product_Name'].str.lower().str.contains(search) | 
                                                        filtered_products_df['Product_ID'].str.lower().str.contains(search)]
        if category != 'All':
            filtered_products_df = filtered_products_df[filtered_products_df['Category'] == category]
            
        ascending = (order == 'asc')
        if sort_by == 'name':
            filtered_products_df = filtered_products_df.sort_values('Product_Name', ascending=ascending)
        elif sort_by == 'price':
            filtered_products_df = filtered_products_df.sort_values('Selling_Price', ascending=ascending)

        active_products_list = filtered_products_df.to_dict(orient='records')

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
                p_id = row['Product_ID']
                p_name = p_id
                
                if not master_products_df.empty:
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
        active_products=active_products_list,
        categories=categories,
        sales_history=grouped_history_list,
        msg=feedback_msg,
        alert_type=alert_type,
        current_search=search,
        current_category=category,
        current_sort=sort_by,
        current_order=order
    )