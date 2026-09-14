# routes/reports.py - Enterprise Operational Command Center & Financial Ledger
from flask import Blueprint, request, redirect, session, render_template, url_for
from modules.database import InventoryDB
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
import sqlite3
import json

reports_bp = Blueprint('reports', __name__)

def ensure_operational_tables_exist(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Operational_Incidents (
            Incident_ID TEXT PRIMARY KEY,
            Date TEXT,
            Type TEXT,
            Staff_Involved TEXT,
            Description TEXT,
            Status TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Capital_Expenditures (
            CapEx_ID TEXT PRIMARY KEY,
            Date TEXT,
            Category TEXT,
            Description TEXT,
            Amount REAL
        )
    """)
    conn.commit()
    conn.close()

def calculate_sales_cogs(sales_slice_df, db_path):
    """
    Computes accurate, multi-tiered Cost of Goods Sold (COGS) across:
    1. Direct Product Recipes (Recipes + Ingredients.Cost_Per_Unit)
    2. Modifier Add-ons (Modifier_Recipes + Ingredients.Cost_Per_Unit)
    3. Products.Cost_Price fallback
    """
    if sales_slice_df is None or sales_slice_df.empty:
        return 0.0
        
    conn = sqlite3.connect(db_path, timeout=20.0)
    cursor = conn.cursor()

    # 1. Product Recipes
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Recipes'")
    prod_recipe_map = defaultdict(list)
    if cursor.fetchone():
        cursor.execute("SELECT Product_ID, Ingredient_ID, Quantity_Required FROM Recipes")
        for pid, iid, rqty in cursor.fetchall():
            prod_recipe_map[str(pid)].append((str(iid), float(rqty or 0.0)))

    # 2. Modifier Recipes
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifier_Recipes'")
    mod_recipe_map = defaultdict(list)
    if cursor.fetchone():
        cursor.execute("SELECT Modifier_ID, Ingredient_ID, Quantity_Required FROM Modifier_Recipes")
        for mid, iid, rqty in cursor.fetchall():
            mod_recipe_map[str(mid)].append((str(iid), float(rqty or 0.0)))

    # 3. Ingredient Costs
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Ingredients'")
    ing_cost_map = {}
    if cursor.fetchone():
        cursor.execute("SELECT Ingredient_ID, Cost_Per_Unit FROM Ingredients")
        for iid, cpu in cursor.fetchall():
            ing_cost_map[str(iid)] = float(cpu or 0.0)

    # 4. Product Cost Price Fallback
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Products'")
    prod_cost_map = {}
    if cursor.fetchone():
        cursor.execute("SELECT Product_ID, Cost_Price FROM Products")
        for pid, cp in cursor.fetchall():
            prod_cost_map[str(pid)] = float(cp or 0.0)

    conn.close()

    total_cogs = 0.0
    for _, s_row in sales_slice_df.iterrows():
        item_id = str(s_row.get('Product_ID', '')).strip()
        try:
            qty_sold = float(s_row.get('Quantity', 0.0) or 0.0)
        except (ValueError, TypeError):
            qty_sold = 0.0

        if qty_sold == 0:
            continue

        if item_id in prod_recipe_map and len(prod_recipe_map[item_id]) > 0:
            for iid, req_qty in prod_recipe_map[item_id]:
                total_cogs += qty_sold * req_qty * ing_cost_map.get(iid, 0.0)
        elif item_id in mod_recipe_map and len(mod_recipe_map[item_id]) > 0:
            for iid, req_qty in mod_recipe_map[item_id]:
                total_cogs += qty_sold * req_qty * ing_cost_map.get(iid, 0.0)
        elif item_id in prod_cost_map and prod_cost_map[item_id] > 0:
            total_cogs += qty_sold * prod_cost_map[item_id]
        elif 'Unit_Cost' in s_row and pd.notnull(s_row['Unit_Cost']):
            total_cogs += qty_sold * float(s_row['Unit_Cost'] or 0.0)

    return round(float(total_cogs), 2)

@reports_bp.route('/portal/<username>/reports', methods=['GET', 'POST'])
def web_reports_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    db_path = f"data/client_{username}.db"
    ensure_operational_tables_exist(db_path)
    db = InventoryDB(db_path)
    
    feedback_msg = None
    alert_type = "success"

    # ==========================================
    # 1. POST METHOD: RECORD OPERATIONAL DATA
    # ==========================================
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        if action == 'add_incident':
            incident_date = request.form.get('incident_date', datetime.now().strftime("%Y-%m-%d")).strip()
            incident_type = request.form.get('incident_type', 'Complaint').strip()
            staff_involved = request.form.get('staff_involved', 'N/A').strip()
            description = request.form.get('description', '').strip()
            status = request.form.get('status', 'Pending').strip()
            
            if not description:
                feedback_msg = "Error: Incident description field cannot be left empty."
                alert_type = "danger"
            else:
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM Operational_Incidents")
                    count = cursor.fetchone()[0]
                    incident_id = f"INC{count + 1:04d}"
                    
                    cursor.execute("""
                        INSERT INTO Operational_Incidents (Incident_ID, Date, Type, Staff_Involved, Description, Status)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (incident_id, incident_date, incident_type, staff_involved, description, status))
                    conn.commit()
                    conn.close()
                    
                    feedback_msg = f"Success: Incident Report {incident_id} successfully logged to operations ledger."
                    alert_type = "success"
                except Exception as e:
                    feedback_msg = f"Database Error logging incident: {str(e)}"
                    alert_type = "danger"
                    
        elif action == 'update_incident_status':
            inc_id = request.form.get('incident_id')
            new_status = request.form.get('new_status')
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE Operational_Incidents SET Status = ? WHERE Incident_ID = ?", (new_status, inc_id))
                conn.commit()
                conn.close()
                feedback_msg = f"Success: Status updated for {inc_id}."
                alert_type = "success"
            except Exception as e:
                feedback_msg = str(e)
                alert_type = "danger"

        elif action == 'add_capex':
            capex_date = request.form.get('capex_date', datetime.now().strftime("%Y-%m-%d")).strip()
            category = request.form.get('category', 'Equipment').strip()
            description = request.form.get('description', '').strip()
            amount_str = request.form.get('amount', '0.0')
            
            try:
                amount = float(amount_str)
                if amount <= 0 or not description:
                    feedback_msg = "Error: Amount must be positive and description is mandatory."
                    alert_type = "danger"
                else:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM Capital_Expenditures")
                    count = cursor.fetchone()[0]
                    capex_id = f"CAP{count + 1:04d}"
                    
                    cursor.execute("""
                        INSERT INTO Capital_Expenditures (CapEx_ID, Date, Category, Description, Amount)
                        VALUES (?, ?, ?, ?, ?)
                    """, (capex_id, capex_date, category, description, amount))
                    conn.commit()
                    conn.close()
                    
                    feedback_msg = f"Success: Capital investment {capex_id} logged to the balance sheet."
                    alert_type = "success"
            except Exception as e:
                feedback_msg = f"Database Error logging CapEx: {str(e)}"
                alert_type = "danger"
                
        elif action == 'delete_capex':
            capex_id = request.form.get('capex_id')
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM Capital_Expenditures WHERE CapEx_ID = ?", (capex_id,))
                conn.commit()
                conn.close()
                feedback_msg = f"Removed: Capital investment {capex_id} successfully deleted from the tracker."
                alert_type = "warning"
            except Exception as e:
                feedback_msg = f"Database Error removing CapEx: {str(e)}"
                alert_type = "danger"

        return redirect(url_for('reports.web_reports_tab', username=username, msg=feedback_msg, alert_type=alert_type))

    # ==========================================
    # 2. GET METHOD: CORE BUSINESS ANALYTICS
    # ==========================================
    url_msg = request.args.get('msg')
    if url_msg:
        feedback_msg = url_msg
        alert_type = request.args.get('alert_type', 'success')

    sales_df = db.read_tab('Sales')
    expenses_df = db.read_tab('Expenses')
    products_df = db.read_tab('Products')
    audit_df = db.read_tab('Inventory_Audit_Log')  
    ingredients_df = db.read_tab('Ingredients')

    if not sales_df.empty:
        sales_df['Total_Amount'] = pd.to_numeric(sales_df['Total_Amount'], errors='coerce').fillna(0.0)
        sales_df['Quantity'] = pd.to_numeric(sales_df['Quantity'], errors='coerce').fillna(0.0)
        
        # Resilient date coalescing prioritizing Sale_Date and Date
        date_candidates = ['Sale_Date', 'sale_date', 'Sales_Date', 'Date', 'date', 'created_at', 'timestamp', 'transaction_date', 'DateTime']
        sales_df['Parsed_Date'] = pd.NaT
        for col in date_candidates:
            if col in sales_df.columns:
                parsed_col = pd.to_datetime(sales_df[col], errors='coerce')
                sales_df['Parsed_Date'] = sales_df['Parsed_Date'].fillna(parsed_col)

    if not expenses_df.empty:
        expenses_df['Amount'] = pd.to_numeric(expenses_df['Amount'], errors='coerce').fillna(0.0)
        date_candidates_exp = ['Expense_Date', 'Date', 'expense_date', 'date', 'created_at', 'timestamp']
        expenses_df['Parsed_Date'] = pd.NaT
        for col in date_candidates_exp:
            if col in expenses_df.columns:
                parsed_col = pd.to_datetime(expenses_df[col], errors='coerce')
                expenses_df['Parsed_Date'] = expenses_df['Parsed_Date'].fillna(parsed_col)

    if not audit_df.empty:
        audit_df['Variance'] = pd.to_numeric(audit_df['Variance'], errors='coerce').fillna(0.0)
        date_candidates_audit = ['Date', 'Log_Date', 'timestamp', 'created_at', 'sales_date', 'DateTime']
        audit_df['Parsed_Date'] = pd.NaT
        for col in date_candidates_audit:
            if col in audit_df.columns:
                parsed_col = pd.to_datetime(audit_df[col], errors='coerce')
                audit_df['Parsed_Date'] = audit_df['Parsed_Date'].fillna(parsed_col)

    # --- ALL-TIME ROI CALCULATIONS BEFORE DATE FILTER ---
    all_time_revenue = float(sales_df['Total_Amount'].sum()) if not sales_df.empty else 0.0
    all_time_expenses = float(expenses_df['Amount'].sum()) if not expenses_df.empty else 0.0
    all_time_cogs = calculate_sales_cogs(sales_df, db_path)

    all_time_net_profit = all_time_revenue - all_time_cogs - all_time_expenses
    
    # CapEx Data
    total_capex = 0.0
    capex_list = []
    try:
        conn = sqlite3.connect(db_path)
        capex_raw_df = pd.read_sql_query("SELECT * FROM Capital_Expenditures ORDER BY Date DESC", conn)
        conn.close()
        if not capex_raw_df.empty:
            total_capex = float(capex_raw_df['Amount'].sum())
            capex_list = capex_raw_df.to_dict(orient='records')
    except:
        pass
        
    roi_percentage = (all_time_net_profit / total_capex) * 100.0 if total_capex > 0 else 0.0
    remaining_roi = max(0.0, total_capex - all_time_net_profit)

    # ==========================================
    # DATE RANGE & ADVANCED FILTER ENGINE
    # ==========================================
    selected_period = request.args.get('period', 'this_month')
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')

    now = datetime.now()
    today_start = now.date()
    current_year = now.year
    current_month = now.month

    start_bound = None
    end_bound = None

    if selected_period == 'today':
        start_bound = pd.to_datetime(today_start)
        end_bound = pd.to_datetime(today_start) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif selected_period in ['this_week', 'week']:
        start_bound = pd.to_datetime(today_start - timedelta(days=today_start.weekday()))
        end_bound = start_bound + pd.Timedelta(days=7) - pd.Timedelta(seconds=1)
    elif selected_period in ['this_month', 'month']:
        start_bound = pd.to_datetime(datetime(current_year, current_month, 1))
        end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif selected_period == 'last_month':
        last_month = 12 if current_month == 1 else current_month - 1
        last_year = current_year - 1 if current_month == 1 else current_year
        start_bound = pd.to_datetime(datetime(last_year, last_month, 1))
        end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif selected_period == 'custom' and start_date_str and end_date_str:
        try:
            start_bound = pd.to_datetime(start_date_str)
            end_bound = pd.to_datetime(end_date_str) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        except Exception:
            selected_period = 'this_month'
            start_bound = pd.to_datetime(datetime(current_year, current_month, 1))
            end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    elif selected_period in ['all_time', 'all']:
        start_bound = None
        end_bound = None
    else:
        selected_period = 'this_month'
        start_bound = pd.to_datetime(datetime(current_year, current_month, 1))
        end_bound = start_bound + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    formatted_start_str = start_bound.strftime("%Y-%m-%d") if start_bound is not None else ""
    formatted_end_str = end_bound.strftime("%Y-%m-%d") if end_bound is not None else ""

    if start_bound is not None and end_bound is not None:
        if not sales_df.empty and 'Parsed_Date' in sales_df.columns:
            sales_df = sales_df[(sales_df['Parsed_Date'] >= start_bound) & (sales_df['Parsed_Date'] <= end_bound)]
        if not expenses_df.empty and 'Parsed_Date' in expenses_df.columns:
            expenses_df = expenses_df[(expenses_df['Parsed_Date'] >= start_bound) & (expenses_df['Parsed_Date'] <= end_bound)]
        if not audit_df.empty and 'Parsed_Date' in audit_df.columns:
            audit_df = audit_df[(audit_df['Parsed_Date'] >= start_bound) & (audit_df['Parsed_Date'] <= end_bound)]

    # CORE REVENUE & COST OF GOODS SOLD (COGS) CALCULATIONS
    total_revenue = float(sales_df['Total_Amount'].sum()) if not sales_df.empty else 0.0
    total_sales_count = len(sales_df) if not sales_df.empty else 0
    total_cogs = calculate_sales_cogs(sales_df, db_path)

    total_expenses = float(expenses_df['Amount'].sum()) if not expenses_df.empty else 0.0

    total_waste_cost = 0.0
    opportunity_cost = 0.0
    
    if not audit_df.empty and not ingredients_df.empty:
        audit_df['Audit_ID'] = audit_df['Audit_ID'].astype(str).str.strip()
        audit_df['Notes'] = audit_df['Notes'].astype(str).fillna('')
        audit_df['Ingredient_Name'] = audit_df['Ingredient_Name'].astype(str).str.strip()
        
        waste_mask = audit_df['Audit_ID'].str.startswith('WST') | audit_df['Audit_ID'].str.startswith('PRD')
        waste_rows = audit_df[waste_mask]
        
        ingredients_df['Ingredient_Name_Clean'] = ingredients_df['Ingredient_Name'].astype(str).str.strip().str.lower()
        
        for _, row in waste_rows.iterrows():
            ing_name_clean = str(row['Ingredient_Name']).strip().lower()
            qty_lost = abs(float(row['Variance']))
            
            ing_match = ingredients_df[ingredients_df['Ingredient_Name_Clean'] == ing_name_clean]
            if not ing_match.empty:
                cost_per_unit = float(pd.to_numeric(ing_match['Cost_Per_Unit'], errors='coerce').fillna(0.0).iloc[0])
                row_financial_cost = qty_lost * cost_per_unit
                total_waste_cost += row_financial_cost
                
                retail_multiplier = 1.0
                if row['Audit_ID'].startswith('PRD') and not products_df.empty:
                    notes_upper = row['Notes'].upper()
                    for _, prod_row in products_df.iterrows():
                        p_id_str = str(prod_row['Product_ID']).upper()
                        p_name_str = str(prod_row['Product_Name']).upper()
                        if p_id_str in notes_upper or p_name_str in notes_upper:
                            s_price = float(prod_row['Selling_Price'])
                            c_price = float(prod_row['Cost_Price']) if float(prod_row['Cost_Price']) > 0 else 1.0
                            retail_multiplier = s_price / c_price
                            break
                elif row['Audit_ID'].startswith('WST'):
                    retail_multiplier = 1.0  
                    
                opportunity_cost += (row_financial_cost * retail_multiplier)

    gross_profit_margin = total_revenue - total_cogs
    net_profit = gross_profit_margin - total_expenses - total_waste_cost

    warehouse_asset_value = 0.0
    if not ingredients_df.empty:
        ingredients_df['Current_Stock'] = pd.to_numeric(ingredients_df['Current_Stock'], errors='coerce').fillna(0.0)
        ingredients_df['Cost_Per_Unit'] = pd.to_numeric(ingredients_df['Cost_Per_Unit'], errors='coerce').fillna(0.0)
        warehouse_asset_value = float((ingredients_df['Current_Stock'] * ingredients_df['Cost_Per_Unit']).sum())

    total_assets = net_profit + warehouse_asset_value
    total_liabilities = 0.0  
    owners_equity = total_assets - total_liabilities

    if total_revenue > 0:
        gross_margin_pct = (gross_profit_margin / total_revenue) * 100.0
    elif not products_df.empty:
        p_temp = products_df.copy()
        p_temp['Selling_Price'] = pd.to_numeric(p_temp['Selling_Price'], errors='coerce').fillna(0.0)
        p_temp['Cost_Price'] = pd.to_numeric(p_temp['Cost_Price'], errors='coerce').fillna(0.0)
        valid_p = p_temp[p_temp['Selling_Price'] > 0]
        if not valid_p.empty:
            gross_margin_pct = float(((valid_p['Selling_Price'] - valid_p['Cost_Price']) / valid_p['Selling_Price']).mean() * 100.0)
        else:
            gross_margin_pct = 65.0
    else:
        gross_margin_pct = 65.0

    if gross_margin_pct <= 0:
        gross_margin_pct = 65.0

    if total_expenses > 0 and gross_margin_pct > 0:
        break_even_target = total_expenses / (gross_margin_pct / 100.0)
    else:
        break_even_target = 0.0

    daily_break_even = break_even_target / 30.0

    if total_sales_count > 0 and total_revenue > 0:
        aov = total_revenue / total_sales_count
    else:
        aov = 150.0  

    daily_tickets_needed = int(round(daily_break_even / aov)) if aov > 0 else 0

    if break_even_target > 0:
        bep_progress_pct = min(100.0, (total_revenue / break_even_target) * 100.0)
    else:
        bep_progress_pct = 0.0

    if total_revenue >= break_even_target and break_even_target > 0:
        bep_status_text = "PROFIT ZONE"
        bep_status_desc = f"Revenue exceeds fixed operating costs by PHP {total_revenue - break_even_target:,.2f}."
        bep_status_color = "#10b981"
        bep_badge_class = "bg-success"
    elif total_revenue >= (break_even_target * 0.8) and break_even_target > 0:
        bep_status_text = "CAUTION ZONE"
        bep_status_desc = f"You need PHP {break_even_target - total_revenue:,.2f} more in gross sales to reach break-even."
        bep_status_color = "#f59e0b"
        bep_badge_class = "bg-warning text-dark"
    else:
        bep_status_text = "LOSS ZONE"
        needed = break_even_target - total_revenue
        bep_status_desc = f"Current revenue is PHP {needed:,.2f} short of covering operating overhead." if break_even_target > 0 else "Log operating expenses and products to calculate your break-even threshold."
        bep_status_color = "#ef4444"
        bep_badge_class = "bg-danger"

    menu_data_json = "[]"
    avg_qty_threshold = 0.0
    avg_margin_threshold = 0.0
    quadrant_counts = {"Stars": 0, "Plowhorses": 0, "Puzzles": 0, "Dogs": 0}
    action_notes = []

    if not products_df.empty:
        products_df['Selling_Price'] = pd.to_numeric(products_df['Selling_Price'], errors='coerce').fillna(0.0)
        products_df['Cost_Price'] = pd.to_numeric(products_df['Cost_Price'], errors='coerce').fillna(0.0)
        products_df['Profit_Margin'] = products_df['Selling_Price'] - products_df['Cost_Price']

        product_metrics = []
        for _, prod in products_df.iterrows():
            p_id = prod['Product_ID']
            prod_qty = float(sales_df[sales_df['Product_ID'] == p_id]['Quantity'].sum()) if not sales_df.empty else 0.0
            product_metrics.append({
                'id': p_id, 'name': prod['Product_Name'], 'qty': prod_qty,
                'margin': float(prod['Profit_Margin']), 'selling_price': float(prod['Selling_Price'])
            })

        if product_metrics:
            avg_qty_threshold = sum(p['qty'] for p in product_metrics) / len(product_metrics)
            avg_margin_threshold = sum(p['margin'] for p in product_metrics) / len(product_metrics)
            chart_points = []
            
            for p in product_metrics:
                if p['qty'] >= avg_qty_threshold and p['margin'] >= avg_margin_threshold: quadrant = "Stars"
                elif p['qty'] >= avg_qty_threshold and p['margin'] < avg_margin_threshold: quadrant = "Plowhorses"
                elif p['qty'] < avg_qty_threshold and p['margin'] >= avg_margin_threshold: quadrant = "Puzzles"
                else: quadrant = "Dogs"

                quadrant_counts[quadrant] += 1
                chart_points.append({'label': p['name'], 'x': p['qty'], 'y': p['margin'], 'quadrant': quadrant, 'selling_price': p['selling_price']})
                
                if quadrant == 'Plowhorses' and p['qty'] > 0:
                    action_notes.append(f"Plowhorse Alert: '{p['name']}' generates high sales volume but thin margins. Re-evaluate ingredient portions or optimize vendor sourcing costs.")
                elif quadrant == 'Puzzles':
                    action_notes.append(f"Puzzle Opportunity: '{p['name']}' has strong gross profitability but slow sales movement. Feature prominently or tie into promotional bundles.")
                    
            menu_data_json = json.dumps(chart_points)

    inflation_data = []
    full_audit_df = db.read_tab('Inventory_Audit_Log')
    
    if not full_audit_df.empty:
        rcv_df = full_audit_df[full_audit_df['Audit_ID'].astype(str).str.startswith('RCV')].copy()
        if not rcv_df.empty:
            rcv_df['Date'] = pd.to_datetime(rcv_df['Date'], errors='coerce')
            rcv_df['Extracted_Price'] = rcv_df['Notes'].astype(str).str.extract(r'Intake Cost: PHP ([\d,\.]+)/unit')[0]
            rcv_df['Extracted_Price'] = pd.to_numeric(rcv_df['Extracted_Price'].astype(str).str.replace(',', ''), errors='coerce')
            rcv_df = rcv_df.dropna(subset=['Extracted_Price', 'Date'])
            rcv_df = rcv_df.sort_values('Date')
            
            if start_bound is not None and end_bound is not None:
                current_period_rcv = rcv_df[(rcv_df['Date'] >= start_bound) & (rcv_df['Date'] <= end_bound)]
            else:
                current_period_rcv = rcv_df
                
            active_ingredients = current_period_rcv['Ingredient_Name'].unique()
            
            for name in active_ingredients:
                ing_all_time = rcv_df[rcv_df['Ingredient_Name'] == name]
                ing_current = current_period_rcv[current_period_rcv['Ingredient_Name'] == name]
                
                if len(ing_all_time) > 1 and not ing_current.empty:
                    oldest_price = float(ing_all_time.iloc[0]['Extracted_Price'])
                    newest_price = float(ing_current.iloc[-1]['Extracted_Price'])
                    
                    if oldest_price > 0 and newest_price > oldest_price:
                        pct_change = ((newest_price - oldest_price) / oldest_price) * 100.0
                        inflation_data.append({
                            'name': name,
                            'old_price': oldest_price,
                            'new_price': newest_price,
                            'pct_change': pct_change,
                            'last_date': ing_current.iloc[-1]['Date'].strftime("%Y-%m-%d")
                        })
            
            inflation_data = sorted(inflation_data, key=lambda x: x['pct_change'], reverse=True)[:5]

    recent_sales = []
    if not sales_df.empty:
        sort_col = 'Parsed_Date' if 'Parsed_Date' in sales_df.columns and sales_df['Parsed_Date'].notna().any() else 'Sale_Date'
        sales_sorted = sales_df.sort_values(sort_col, ascending=False).head(8)
        for _, row in sales_sorted.iterrows():
            p_id = str(row.get('Product_ID', ''))
            stored_name = row.get('Product_Name')
            if stored_name and str(stored_name).strip() and str(stored_name).strip().lower() != 'nan':
                p_name = str(stored_name).strip()
            elif not products_df.empty and p_id in products_df['Product_ID'].values:
                p_name = products_df[products_df['Product_ID'] == p_id]['Product_Name'].values[0]
            else:
                p_name = p_id

            date_val = row.get('Parsed_Date')
            if pd.notnull(date_val):
                date_str = pd.to_datetime(date_val).strftime("%Y-%m-%d")
            else:
                date_str = str(row.get('Sale_Date', datetime.now().strftime("%Y-%m-%d")))
                
            recent_sales.append({
                'Sale_Date': date_str, 'Sale_Time': str(row.get('Sale_Time', '')),
                'Product_Name': p_name, 'Quantity': float(row.get('Quantity', 0.0) or 0.0), 'Total_Amount': float(row.get('Total_Amount', 0.0) or 0.0)
            })

    incidents_list = []
    try:
        conn = sqlite3.connect(db_path)
        inc_df = pd.read_sql_query("SELECT * FROM Operational_Incidents ORDER BY Date DESC", conn)
        conn.close()
        if not inc_df.empty:
            incidents_list = inc_df.to_dict(orient='records')
    except:
        pass

    return render_template(
        'reports.html',
        username=username,
        total_revenue=total_revenue,
        total_cogs=total_cogs,
        gross_margin=gross_profit_margin,
        total_expenses=total_expenses,
        waste_cost=total_waste_cost,
        opportunity_cost=opportunity_cost,
        warehouse_asset=warehouse_asset_value,
        net_profit=net_profit,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        owners_equity=owners_equity,
        recent_sales=recent_sales,
        incidents=incidents_list,
        current_period=selected_period,
        start_date=start_date_str if start_date_str else formatted_start_str,
        end_date=end_date_str if end_date_str else formatted_end_str,
        menu_data_json=menu_data_json,
        avg_qty=avg_qty_threshold,
        avg_margin=avg_margin_threshold,
        quadrants=quadrant_counts,
        advice=action_notes[:4],
        inflation_data=inflation_data,
        msg=feedback_msg,
        alert_type=alert_type,
        now=now,
        gross_margin_pct=gross_margin_pct,
        break_even_target=break_even_target,
        daily_break_even=daily_break_even,
        aov=aov,
        daily_tickets_needed=daily_tickets_needed,
        bep_progress_pct=bep_progress_pct,
        bep_status_text=bep_status_text,
        bep_status_desc=bep_status_desc,
        bep_status_color=bep_status_color,
        bep_badge_class=bep_badge_class,
        total_capex=total_capex,
        all_time_net_profit=all_time_net_profit,
        roi_percentage=roi_percentage,
        remaining_roi=remaining_roi,
        capex_list=capex_list
    )