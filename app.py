# app.py - COMPLETE MAIN CORE SAAS ENGINE WITH INTEGRATED ANALYTICS, LOGBOOK & MENU ENGINEERING
from flask import Flask, redirect, session, render_template, request
from modules.database import InventoryDB
import sqlite3
import os
import pandas as pd
import datetime

# SYSTEM COMPONENT BLUEPRINT IMPORTS
from routes.auth import auth_bp
from routes.ingredients import ingredients_bp
from routes.products import products_bp
from routes.recipes import recipes_bp
from routes.sales import sales_bp
from routes.inventory import inventory_bp
from routes.expenses import expenses_bp
from routes.reports import reports_bp
from routes.settings import settings_bp
from routes.admin import admin_bp

app = Flask(__name__)
app.secret_key = 'knife-and-ember-secret-saas-key'

# MOUNT ALL COMPONENT BLUEPRINTS
app.register_blueprint(auth_bp)
app.register_blueprint(ingredients_bp)
app.register_blueprint(products_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(expenses_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(admin_bp)

USER_DB_PATH = "data/users.db"

def initialize_user_database():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(USER_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password TEXT NOT NULL, database_file TEXT NOT NULL, subscription_status TEXT NOT NULL
        )
    ''')
    cursor.execute("INSERT OR REPLACE INTO users VALUES ('bakery', 'bakery123', 'data/client_bakery.db', 'Active')")
    conn.commit()
    conn.close()

initialize_user_database()

@app.route('/')
def home_redirect():
    if session.get('logged_in_user'):
        return redirect(f"/portal/{session['logged_in_user']}")
    return redirect('/login')

@app.route('/portal/<username>')
def client_portal(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    # 1. Fetch Structural Data Foundations
    products_df = client_db.get_all_products()
    total_products = len(products_df) if not products_df.empty else 0
    
    inventory_df = client_db.get_inventory_status()
    low_stock_count = len(inventory_df[inventory_df['Status'] == 'Low Stock']) if not inventory_df.empty else 0
    
    # 2. Date Filter Parsing Controls (Loyverse Style Alignment)
    selected_period = request.args.get('period', 'this_month')
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    
    now = datetime.datetime.now()
    today_start = now.date()
    
    if selected_period == 'today':
        start_bound = pd.to_datetime(today_start)
        end_bound = pd.to_datetime(today_start) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif selected_period == 'this_week':
        start_bound = pd.to_datetime(today_start - datetime.timedelta(days=today_start.weekday()))
        end_bound = start_bound + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)
    elif selected_period == 'custom' and start_date_str and end_date_str:
        try:
            start_bound = pd.to_datetime(start_date_str)
            end_bound = pd.to_datetime(end_date_str) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        except Exception:
            selected_period = 'this_month'
            start_bound = pd.to_datetime(datetime.date(now.year, now.month, 1))
            end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    else:
        selected_period = 'this_month'
        start_bound = pd.to_datetime(datetime.date(now.year, now.month, 1))
        end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    formatted_start_str = start_bound.strftime("%Y-%m-%d")
    formatted_end_str = end_bound.strftime("%Y-%m-%d")

    # 3. Process Sales Streams & Formulate Timeline Graph
    sales_df = client_db.read_tab('Sales')
    total_revenue = 0.0
    chart_labels = []
    chart_data = []
    sales_count = 0

    if not sales_df.empty and 'Total_Amount' in sales_df.columns:
        sales_df['Total_Amount'] = pd.to_numeric(sales_df['Total_Amount'], errors='coerce').fillna(0.0)
        
        # Flexibly detect any common date column name across system variations
        possible_date_cols = ['Sales_Date', 'Date', 'sales_date', 'date', 'created_at', 'timestamp', 'transaction_date', 'DateTime']
        date_col = next((col for col in possible_date_cols if col in sales_df.columns), None)
        
        if date_col:
            sales_df['Parsed_Date'] = pd.to_datetime(sales_df[date_col], errors='coerce')
            filtered_sales = sales_df[(sales_df['Parsed_Date'] >= start_bound) & (sales_df['Parsed_Date'] <= end_bound)]
            
            # Fallback to full dataset if date filter returns an empty slice
            if filtered_sales.empty and not sales_df.empty:
                filtered_sales = sales_df.copy()

            total_revenue = float(filtered_sales['Total_Amount'].sum())
            sales_count = len(filtered_sales)
            
            if selected_period == 'today':
                filtered_sales['Hour_Block'] = filtered_sales['Parsed_Date'].dt.strftime('%I:%M %p')
                hourly_group = filtered_sales.groupby('Hour_Block')['Total_Amount'].sum()
                chart_labels = list(hourly_group.index)
                chart_data = [float(v) for v in hourly_group.values]
            else:
                filtered_sales['Day_Block'] = filtered_sales['Parsed_Date'].dt.strftime('%b %d')
                daily_group = filtered_sales.groupby('Day_Block')['Total_Amount'].sum()
                chart_labels = list(daily_group.index)
                chart_data = [float(v) for v in daily_group.values]
        else:
            total_revenue = float(sales_df['Total_Amount'].sum())
            sales_count = len(sales_df)
            chart_labels = ['Total Aggregate']
            chart_data = [total_revenue]

    if not chart_labels:
        chart_labels = ['08:00 AM', '12:00 PM', '04:00 PM', '08:00 PM'] if selected_period == 'today' else ['Period Start', 'Period End']
        chart_data = [0.0, 0.0, 0.0, 0.0] if selected_period == 'today' else [0.0, 0.0]

    # 4. Process Expenses Matrix & Generate Doughnut Chart Data Arrays
    expenses_df = client_db.read_tab('Expenses')
    total_expenses = 0.0
    expense_categories = []
    expense_values = []
    
    if not expenses_df.empty and 'Amount' in expenses_df.columns:
        expenses_df['Amount'] = pd.to_numeric(expenses_df['Amount'], errors='coerce').fillna(0.0)
        date_col_exp = 'Expense_Date' if 'Expense_Date' in expenses_df.columns else ('Date' if 'Date' in expenses_df.columns else None)
        
        if date_col_exp:
            expenses_df['Parsed_Date'] = pd.to_datetime(expenses_df[date_col_exp], errors='coerce')
            filtered_exp = expenses_df[(expenses_df['Parsed_Date'] >= start_bound) & (expenses_df['Parsed_Date'] <= end_bound)]
            total_expenses = float(filtered_exp['Amount'].sum())
            
            if not filtered_exp.empty:
                cat_group = filtered_exp.groupby('Category')['Amount'].sum()
                expense_categories = list(cat_group.index)
                expense_values = [float(v) for v in cat_group.values]
        else:
            total_expenses = float(expenses_df['Amount'].sum())
            cat_group = expenses_df.groupby('Category')['Amount'].sum()
            expense_categories = list(cat_group.index)
            expense_values = [float(v) for v in cat_group.values]

    # 5. Strategic Menu Engineering Matrix Engine
    menu_engineering_list = []
    if not products_df.empty:
        products_df['Selling_Price'] = pd.to_numeric(products_df['Selling_Price'], errors='coerce').fillna(0.0)
        products_df['Cost_Price'] = pd.to_numeric(products_df['Cost_Price'], errors='coerce').fillna(0.0)
        products_df['Margin_Amt'] = products_df['Selling_Price'] - products_df['Cost_Price']
        
        avg_margin = products_df['Margin_Amt'].mean() if len(products_df) > 0 else 0.0
        
        item_sales_map = {}
        if not sales_df.empty and 'Product_ID' in sales_df.columns:
            item_sales_map = sales_df['Product_ID'].value_counts().to_dict()
            
        for _, row in products_df.head(5).iterrows():
            prod_id = row.get('Product_ID', '')
            prod_name = row.get('Product_Name', 'Unknown Item')
            margin_amt = float(row['Margin_Amt'])
            
            # Use actual sales volume from map, default to 0 for clean accounts
            sales_volume = int(item_sales_map.get(prod_id, 0))
            
            if margin_amt >= avg_margin and sales_volume >= 8:
                classification = "Star"
                strategy = "Core Pillar: Maintain Quality & Position"
                badge_class = "success"
            elif margin_amt >= avg_margin and sales_volume < 8:
                classification = "Push More"
                strategy = "Puzzle: Needs Staff Upselling & Promo"
                badge_class = "info"
            elif margin_amt < avg_margin and sales_volume >= 8:
                classification = "Plowhorse"
                strategy = "Volume Driver: Adjust Price or Portions"
                badge_class = "warning"
            else:
                classification = "Dog"
                strategy = "Underperformer: Review or Phase Out"
                badge_class = "danger"
                
            menu_engineering_list.append({
                'name': prod_name,
                'category': row.get('Category', 'General'),
                'volume': sales_volume,
                'classification': classification,
                'strategy': strategy,
                'badge': badge_class,
                'price': float(row['Selling_Price'])
            })
            
    menu_engineering_list = sorted(menu_engineering_list, key=lambda x: x['volume'], reverse=True)

    # 6. Real-Time Operational Activity Stream (The Shift Manager Logbook)
    logbook_stream = []
    
    # Read primary audit ledger table (with fallback to inventory_log)
    audit_log_df = client_db.read_tab('Inventory_Audit_Log')
    if audit_log_df is None or audit_log_df.empty:
        audit_log_df = client_db.read_tab('Inventory_Log')

    if audit_log_df is not None and not audit_log_df.empty:
        for _, row in audit_log_df.tail(30).iterrows():
            audit_id = str(row.get('Audit_ID', row.get('Type', ''))).strip().upper()
            notes_str = str(row.get('Notes', row.get('Reason', 'Routine process record.'))).strip()
            item_ref = str(row.get('Ingredient_Name', row.get('Ingredient_ID', row.get('Item_Name', 'Stock Line')))).strip()
            
            qty_val = row.get('Variance', row.get('Quantity_Changed', row.get('Quantity', 0)))
            try:
                qty_acted = float(qty_val or 0)
            except Exception:
                qty_acted = 0.0

            log_date_raw = str(row.get('Date', row.get('Log_Date', '')))
            try:
                parsed_log_date = pd.to_datetime(log_date_raw)
                if parsed_log_date < start_bound or parsed_log_date > end_bound:
                    continue
                time_stamp_str = parsed_log_date.strftime("%b %d, %I:%M %p")
            except Exception:
                time_stamp_str = "Today, On Shift"

            user_node = str(row.get('Updated_By', row.get('User', 'Floor Terminal'))).title()

            is_pos_sale = (
                audit_id.startswith('POS') or 
                'POS' in notes_str or 
                ('Product ' in notes_str and 'Product Waste' not in notes_str) or 
                ('PROD' in audit_id and 'Product Waste' not in notes_str and 'WST' not in audit_id)
            )
            is_waste = (
                audit_id.startswith('WST') or 
                'Product Waste:' in notes_str or 
                'Reason:' in notes_str or 
                'SPOIL' in audit_id or 
                'WASTE' in audit_id
            )
            is_prep = (
                audit_id.startswith('PRP') or 
                'PREP' in audit_id or 
                'Consumed to manufacture' in notes_str or 
                'Yielded output' in notes_str
            )

            if is_pos_sale:
                badge_color = "info"
                log_type = "POS SALE"
                event_title = f"POS Recipe Depletion for {item_ref}"
            elif is_waste:
                badge_color = "danger"
                log_type = "SPOILAGE"
                event_title = f"Spoilage/Waste Event recorded for {item_ref}"
            elif is_prep:
                badge_color = "warning"
                log_type = "KITCHEN PREP"
                event_title = f"Kitchen Prep batch finalized for {item_ref}"
            elif qty_acted > 0 or audit_id.startswith('RCV') or audit_id.startswith('AUD'):
                badge_color = "success"
                log_type = "STOCK INTAKE" if audit_id.startswith('RCV') else "AUDIT RECON"
                event_title = f"Stock level addition logged for {item_ref}"
            else:
                badge_color = "danger" if qty_acted < 0 else "success"
                log_type = "ADJUSTMENT"
                event_title = f"Stock level adjustment for {item_ref}"

            logbook_stream.append({
                'timestamp': time_stamp_str,
                'type': log_type,
                'title': event_title,
                'quantity': f"{qty_acted:+,g}" if qty_acted != 0 else "0",
                'user': user_node,
                'badge': badge_color,
                'notes': notes_str
            })

    logbook_stream = list(reversed(logbook_stream))

    return render_template(
        'dashboard.html', username=username, total_products=total_products,
        total_revenue=total_revenue, low_stock_count=low_stock_count, total_expenses=total_expenses,
        error_msg=request.args.get('error', ''),
        current_period=selected_period,
        start_date=formatted_start_str,
        end_date=formatted_end_str,
        chart_labels=chart_labels,
        chart_data=chart_data,
        expense_categories=expense_categories,
        expense_values=expense_values,
        menu_matrix=menu_engineering_list,
        logbook=logbook_stream,
        sales_count=sales_count
    )

if __name__ == '__main__':
    app.run(debug=True)