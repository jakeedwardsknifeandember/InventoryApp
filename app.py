# app.py - COMPLETE MAIN CORE SAAS ENGINE WITH INTEGRATED ANALYTICS, LOGBOOK & MENU ENGINEERING
from flask import Flask, redirect, session, render_template, request, flash
from modules.database import InventoryDB
import sqlite3
import os
import pandas as pd
import datetime
from collections import defaultdict, OrderedDict

# SYSTEM COMPONENT BLUEPRINT IMPORTS
from routes.auth import auth_bp
from routes.ingredients import ingredients_bp
from routes.products import products_bp
from routes.categories import categories_bp
from routes.modifiers import modifiers_bp
from routes.discounts import discounts_bp
from routes.recipes import recipes_bp
from routes.sales import sales_bp
from routes.inventory import inventory_bp
from routes.expenses import expenses_bp
from routes.reports import reports_bp
from routes.settings import settings_bp
from routes.admin import admin_bp
from routes.corrections import corrections_bp
from routes.pos import pos_bp

app = Flask(__name__)
app.secret_key = 'knife-and-ember-secret-saas-key'

# MOUNT ALL COMPONENT BLUEPRINTS
app.register_blueprint(auth_bp)
app.register_blueprint(ingredients_bp)
app.register_blueprint(products_bp)
app.register_blueprint(categories_bp)
app.register_blueprint(modifiers_bp)
app.register_blueprint(discounts_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(expenses_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(corrections_bp)
app.register_blueprint(pos_bp)

USER_DB_PATH = "data/users.db"

def initialize_user_database():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(USER_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password TEXT NOT NULL, database_file TEXT NOT NULL, subscription_status TEXT NOT NULL
        )
    """)
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
    
    # 2. Date Filter Parsing Controls
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
    theoretical_cogs = 0.0

    if not sales_df.empty and 'Total_Amount' in sales_df.columns:
        sales_df['Total_Amount'] = pd.to_numeric(sales_df['Total_Amount'], errors='coerce').fillna(0.0)
        
        # Resilient date coalescing prioritizing Sale_Date and Date
        date_candidates = ['Sale_Date', 'sale_date', 'Sales_Date', 'Date', 'date', 'created_at', 'timestamp', 'transaction_date', 'DateTime']
        sales_df['Parsed_Date'] = pd.NaT
        for col in date_candidates:
            if col in sales_df.columns:
                parsed_col = pd.to_datetime(sales_df[col], errors='coerce')
                sales_df['Parsed_Date'] = sales_df['Parsed_Date'].fillna(parsed_col)

        if sales_df['Parsed_Date'].notna().any():
            filtered_sales = sales_df[(sales_df['Parsed_Date'] >= start_bound) & (sales_df['Parsed_Date'] <= end_bound)].copy()
        else:
            filtered_sales = sales_df.copy()

        total_revenue = float(filtered_sales['Total_Amount'].sum())
        sales_count = len(filtered_sales)
        
        if not filtered_sales.empty and sales_df['Parsed_Date'].notna().any():
            filtered_sales = filtered_sales.sort_values('Parsed_Date')
            if selected_period == 'today':
                filtered_sales['Hour_Num'] = filtered_sales['Parsed_Date'].dt.hour
                hourly_group = filtered_sales.groupby('Hour_Num')['Total_Amount'].sum()
                chart_labels = [datetime.time(h, 0).strftime('%I:%M %p') for h in hourly_group.index]
                chart_data = [float(v) for v in hourly_group.values]
            else:
                filtered_sales['Date_Only'] = filtered_sales['Parsed_Date'].dt.date
                daily_group = filtered_sales.groupby('Date_Only')['Total_Amount'].sum()
                chart_labels = [d.strftime('%b %d') for d in daily_group.index]
                chart_data = [float(v) for v in daily_group.values]

        # -------------------------------------------------------------
        # COMPREHENSIVE THEORETICAL COGS (RECIPES + MODIFIER RECIPES)
        # -------------------------------------------------------------
        if not filtered_sales.empty:
            conn = sqlite3.connect(client_db_path, timeout=20.0)
            cursor = conn.cursor()

            # Product Recipes
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Recipes'")
            prod_recipe_map = defaultdict(list)
            if cursor.fetchone():
                cursor.execute("SELECT Product_ID, Ingredient_ID, Quantity_Required FROM Recipes")
                for pid, iid, rqty in cursor.fetchall():
                    prod_recipe_map[str(pid)].append((str(iid), float(rqty or 0.0)))

            # Modifier Recipes
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifier_Recipes'")
            mod_recipe_map = defaultdict(list)
            if cursor.fetchone():
                cursor.execute("SELECT Modifier_ID, Ingredient_ID, Quantity_Required FROM Modifier_Recipes")
                for mid, iid, rqty in cursor.fetchall():
                    mod_recipe_map[str(mid)].append((str(iid), float(rqty or 0.0)))

            # Ingredient Costs
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Ingredients'")
            ing_cost_map = {}
            if cursor.fetchone():
                cursor.execute("SELECT Ingredient_ID, Cost_Per_Unit FROM Ingredients")
                for iid, cpu in cursor.fetchall():
                    ing_cost_map[str(iid)] = float(cpu or 0.0)

            # Product Cost Price Fallback
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Products'")
            prod_cost_map = {}
            if cursor.fetchone():
                cursor.execute("SELECT Product_ID, Cost_Price FROM Products")
                for pid, cp in cursor.fetchall():
                    prod_cost_map[str(pid)] = float(cp or 0.0)

            conn.close()

            for _, s_row in filtered_sales.iterrows():
                item_id = str(s_row.get('Product_ID', '')).strip()
                try:
                    qty_sold = float(s_row.get('Quantity', 0.0) or 0.0)
                except (ValueError, TypeError):
                    qty_sold = 0.0

                if qty_sold == 0:
                    continue

                if item_id in prod_recipe_map and len(prod_recipe_map[item_id]) > 0:
                    for iid, req_qty in prod_recipe_map[item_id]:
                        theoretical_cogs += qty_sold * req_qty * ing_cost_map.get(iid, 0.0)
                elif item_id in mod_recipe_map and len(mod_recipe_map[item_id]) > 0:
                    for iid, req_qty in mod_recipe_map[item_id]:
                        theoretical_cogs += qty_sold * req_qty * ing_cost_map.get(iid, 0.0)
                elif item_id in prod_cost_map and prod_cost_map[item_id] > 0:
                    theoretical_cogs += qty_sold * prod_cost_map[item_id]

            theoretical_cogs = round(float(theoretical_cogs), 2)

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
        possible_date_cols_exp = ['Expense_Date', 'Date', 'expense_date', 'date', 'created_at', 'timestamp']
        date_col_exp = next((col for col in possible_date_cols_exp if col in expenses_df.columns), None)
        
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
        avg_volume = 1.0
        
        if not sales_df.empty and 'Product_ID' in sales_df.columns:
            item_sales_map = sales_df['Product_ID'].value_counts().to_dict()
            if len(products_df) > 0:
                avg_volume = max(sum(item_sales_map.values()) / len(products_df), 1.0)
            
        for _, row in products_df.iterrows():
            prod_id = row.get('Product_ID', '')
            prod_name = row.get('Product_Name', 'Unknown Item')
            margin_amt = float(row['Margin_Amt'])
            
            sales_volume = int(item_sales_map.get(prod_id, 0))
            
            if margin_amt >= avg_margin and sales_volume >= avg_volume:
                classification = "Star"
                strategy = "Core Pillar: Maintain Quality & Position"
                badge_class = "success"
            elif margin_amt >= avg_margin and sales_volume < avg_volume:
                classification = "Push More"
                strategy = "Puzzle: Needs Staff Upselling & Promo"
                badge_class = "info"
            elif margin_amt < avg_margin and sales_volume >= avg_volume:
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
            
    menu_engineering_list = sorted(menu_engineering_list, key=lambda x: x['volume'], reverse=True)[:10]

    # 6. Real-Time Operational Activity Stream & Waste Shrinkage Valuation
    logbook_stream = []
    total_waste_cost = 0.0
    
    audit_log_df = client_db.read_tab('Inventory_Audit_Log')
    if audit_log_df is None or audit_log_df.empty:
        audit_log_df = client_db.read_tab('Inventory_Log')

    ingredients_pool = client_db.read_tab('Ingredients')
    ing_cost_lookup = {}
    if ingredients_pool is not None and not ingredients_pool.empty:
        ing_cost_lookup = dict(zip(
            ingredients_pool['Ingredient_Name'].astype(str).str.strip().str.lower(),
            pd.to_numeric(ingredients_pool.get('Cost_Per_Unit', 0.0), errors='coerce').fillna(0.0)
        ))

    if audit_log_df is not None and not audit_log_df.empty:
        possible_audit_date_cols = ['Date', 'Log_Date', 'timestamp', 'created_at', 'sales_date', 'DateTime']
        audit_date_col = next((col for col in possible_audit_date_cols if col in audit_log_df.columns), None)

        if audit_date_col:
            audit_log_df['Parsed_Date'] = pd.to_datetime(audit_log_df[audit_date_col], errors='coerce')
            filtered_audit_df = audit_log_df[(audit_log_df['Parsed_Date'] >= start_bound) & (audit_log_df['Parsed_Date'] <= end_bound)].copy()
        else:
            filtered_audit_df = audit_log_df.copy()

        grouped_events = OrderedDict()

        for _, row in filtered_audit_df.iterrows():
            audit_id = str(row.get('Audit_ID', row.get('Type', ''))).strip().upper()
            notes_str = str(row.get('Notes', row.get('Reason', 'Routine process record.'))).strip()
            item_ref = str(row.get('Ingredient_Name', row.get('Ingredient_ID', row.get('Item_Name', 'Stock Line')))).strip()
            
            qty_val = row.get('Variance', row.get('Quantity_Changed', row.get('Quantity', 0)))
            try:
                qty_acted = float(qty_val or 0)
            except Exception:
                qty_acted = 0.0

            # Compute operational waste loss across manual waste, products scrapped, and physical count deficits
            is_waste_event = (
                audit_id.startswith('WST') or 
                audit_id.startswith('PRD') or 
                (audit_id.startswith('AUD') and qty_acted < 0)
            )
            if is_waste_event:
                clean_ing_name = item_ref.strip().lower()
                cpu = float(ing_cost_lookup.get(clean_ing_name, 0.0))
                total_waste_cost += (abs(qty_acted) * cpu)

            parsed_log_date = row.get('Parsed_Date') if 'Parsed_Date' in row else None
            if pd.notnull(parsed_log_date):
                time_stamp_str = parsed_log_date.strftime("%b %d, %I:%M %p")
            else:
                log_date_raw = str(row.get('Date', row.get('Log_Date', '')))
                try:
                    time_stamp_str = pd.to_datetime(log_date_raw).strftime("%b %d, %I:%M %p")
                except Exception:
                    time_stamp_str = "Today, On Shift"

            # Grouping key collapses all ingredients belonging to the exact same transaction
            if audit_id and audit_id not in ['NONE', 'NAN', '']:
                group_key = audit_id
            else:
                group_key = f"{time_stamp_str}_{notes_str[:30]}"

            if group_key not in grouped_events:
                is_pos_sale = (
                    audit_id.startswith('POS') or 
                    audit_id.startswith('SAL') or 
                    audit_id.startswith('MOD') or 
                    'POS' in notes_str or 
                    ('Product ' in notes_str and 'Product Waste' not in notes_str)
                )
                is_manual_waste = (
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
                is_void = (
                    audit_id.startswith('VOID') or 
                    'VOID' in notes_str
                )
                is_audit_deficit = audit_id.startswith('AUD') and qty_acted < 0
                is_audit_surplus = audit_id.startswith('AUD') and qty_acted >= 0

                if is_void:
                    badge_color = "warning"
                    log_type = "VOID RESTORE"
                elif is_pos_sale:
                    badge_color = "primary"
                    log_type = "POS SALE"
                elif is_audit_deficit:
                    badge_color = "danger"
                    log_type = "SHRINKAGE"
                elif is_manual_waste:
                    badge_color = "danger"
                    log_type = "SPOILAGE"
                elif is_prep:
                    badge_color = "warning"
                    log_type = "KITCHEN PREP"
                elif qty_acted > 0 or audit_id.startswith('RCV') or is_audit_surplus:
                    badge_color = "success"
                    log_type = "STOCK INTAKE" if audit_id.startswith('RCV') else "AUDIT SURPLUS"
                else:
                    badge_color = "danger" if qty_acted < 0 else "success"
                    log_type = "ADJUSTMENT"

                commentary = ""
                if "POS Depletion:" in notes_str:
                    parts = notes_str.split('|')
                    sold_item = parts[0].replace("POS Depletion:", "").strip()
                    event_title = f"POS Depletion for {sold_item}"
                    if len(parts) > 1:
                        commentary = "|".join(parts[1:]).strip()
                elif "VOID RESTORE:" in notes_str:
                    parts = notes_str.split('|')
                    event_title = parts[0].strip()
                    if len(parts) > 1:
                        commentary = "|".join(parts[1:]).strip()
                elif is_pos_sale:
                    event_title = f"POS Depletion for Order {audit_id}"
                    commentary = notes_str
                elif is_audit_deficit:
                    event_title = f"Audit Discrepancy Deficit for {item_ref}"
                    commentary = notes_str
                elif is_audit_surplus:
                    event_title = f"Audit Discrepancy Surplus for {item_ref}"
                    commentary = notes_str
                elif is_manual_waste:
                    event_title = f"Spoilage Event recorded for {item_ref}"
                    commentary = notes_str
                elif is_prep:
                    event_title = f"Kitchen Prep batch finalized for {item_ref}"
                    commentary = notes_str
                elif qty_acted > 0 or audit_id.startswith('RCV'):
                    event_title = f"Stock level addition logged for {item_ref}"
                    commentary = notes_str
                else:
                    event_title = f"Stock level adjustment for {item_ref}"
                    commentary = notes_str

                grouped_events[group_key] = {
                    'event_id': group_key,
                    'timestamp': time_stamp_str,
                    'type': log_type,
                    'title': event_title,
                    'user': str(row.get('Updated_By', row.get('User', 'Floor Terminal'))).title(),
                    'badge': badge_color,
                    'notes': commentary,
                    'depleted_items': []
                }

            grouped_events[group_key]['depleted_items'].append({
                'name': item_ref,
                'quantity': f"{qty_acted:+,g}" if qty_acted != 0 else "0"
            })

        logbook_stream = list(reversed(list(grouped_events.values())))[:30]

    total_waste_cost = round(total_waste_cost, 2)

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
        sales_count=sales_count,
        theoretical_cogs=theoretical_cogs,
        total_waste=total_waste_cost
    )

# AUDIT LOG ROUTE: View operational ledger with date filtering
@app.route('/portal/<username>/audit-log')
def audit_log(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    # Access Control: Managers & Platform Admins only
    if session.get('staff_role') not in ['Platform Owner Admin', 'Store Manager']:
        flash('Unauthorized access to Audit Logs.', 'danger')
        return redirect(f"/portal/{username}")

    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)

    selected_period = request.args.get('period', 'this_month')
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')

    now = datetime.datetime.now()
    today_start = now.date()

    start_bound = None
    end_bound = None

    if selected_period == 'today':
        start_bound = pd.to_datetime(today_start)
        end_bound = pd.to_datetime(today_start) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif selected_period == 'this_week':
        start_bound = pd.to_datetime(today_start - datetime.timedelta(days=today_start.weekday()))
        end_bound = start_bound + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)
    elif selected_period == 'this_month':
        start_bound = pd.to_datetime(datetime.date(now.year, now.month, 1))
        end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif selected_period == 'custom' and start_date_str and end_date_str:
        try:
            start_bound = pd.to_datetime(start_date_str)
            end_bound = pd.to_datetime(end_date_str) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        except Exception:
            selected_period = 'all'
            start_bound = None
            end_bound = None
    elif selected_period == 'all':
        start_bound = None
        end_bound = None
    else:
        selected_period = 'this_month'
        start_bound = pd.to_datetime(datetime.date(now.year, now.month, 1))
        end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    formatted_start_str = start_bound.strftime("%Y-%m-%d") if start_bound is not None else ""
    formatted_end_str = end_bound.strftime("%Y-%m-%d") if end_bound is not None else ""

    audit_log_df = client_db.read_tab('Inventory_Audit_Log')
    if audit_log_df is None or audit_log_df.empty:
        audit_log_df = client_db.read_tab('Inventory_Log')

    logs = []
    if audit_log_df is not None and not audit_log_df.empty:
        possible_date_cols = ['Date', 'Log_Date', 'timestamp', 'created_at', 'sales_date']
        date_col = next((col for col in possible_date_cols if col in audit_log_df.columns), None)

        if date_col and start_bound is not None and end_bound is not None:
            audit_log_df['Parsed_Date'] = pd.to_datetime(audit_log_df[date_col], errors='coerce')
            filtered_df = audit_log_df[(audit_log_df['Parsed_Date'] >= start_bound) & (audit_log_df['Parsed_Date'] <= end_bound)].drop(columns=['Parsed_Date'], errors='ignore')
        else:
            filtered_df = audit_log_df.copy()

        logs = filtered_df.to_dict(orient='records')
        logs.reverse()

    return render_template(
        'audit_log.html', 
        username=username, 
        logs=logs,
        current_period=selected_period,
        start_date=start_date_str if start_date_str else formatted_start_str,
        end_date=end_date_str if end_date_str else formatted_end_str
    )

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)