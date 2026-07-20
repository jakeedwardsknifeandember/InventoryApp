# routes/reports.py - Enterprise Operational Command Center & Financial Ledger
from flask import Blueprint, request, redirect, session, render_template, url_for
from modules.database import InventoryDB
from datetime import datetime
import pandas as pd
import sqlite3
import json

reports_bp = Blueprint('reports', __name__)

def ensure_operational_tables_exist(db_path):
    """Dynamically provisions the HR & Incident tracking tables without breaking legacy schemas"""
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
    conn.commit()
    conn.close()

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
    # 📥 1. POST METHOD: RECORD OPERATIONAL INCIDENTS
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
                feedback_msg = "❌ Error: Incident description field cannot be left empty."
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
                    
                    feedback_msg = f"✅ Incident Report {incident_id} successfully logged to operations ledger."
                    alert_type = "success"
                except Exception as e:
                    feedback_msg = f"❌ Database Error logging incident: {str(e)}"
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
                feedback_msg = f"💼 Status updated for {inc_id}."
                alert_type = "success"
            except Exception as e:
                feedback_msg = str(e)
                alert_type = "danger"

        return redirect(url_for('reports.web_reports_tab', username=username, msg=feedback_msg, alert_type=alert_type))

    # ==========================================
    # 📤 2. GET METHOD: CORE BUSINESS ANALYTICS
    # ==========================================
    url_msg = request.args.get('msg')
    if url_msg:
        feedback_msg = url_msg
        alert_type = request.args.get('alert_type', 'success')

    # Read base tables directly matching verified database layout names
    sales_df = db.read_tab('Sales')
    expenses_df = db.read_tab('Expenses')
    products_df = db.read_tab('Products')
    audit_df = db.read_tab('Inventory_Audit_Log')  
    ingredients_df = db.read_tab('Ingredients')

    selected_period = request.args.get('period', 'this_month')
    now = datetime.now()
    current_year = now.year
    current_month = now.month

    # Clean and safely cast columns to appropriate numeric/date datatypes
    if not sales_df.empty:
        sales_df['Total_Amount'] = pd.to_numeric(sales_df['Total_Amount'], errors='coerce').fillna(0.0)
        sales_df['Quantity'] = pd.to_numeric(sales_df['Quantity'], errors='coerce').fillna(0.0)
        sales_df['Sale_Date'] = pd.to_datetime(sales_df['Sale_Date'], errors='coerce')
    if not expenses_df.empty:
        expenses_df['Amount'] = pd.to_numeric(expenses_df['Amount'], errors='coerce').fillna(0.0)
        expenses_df['Expense_Date'] = pd.to_datetime(expenses_df['Expense_Date'], errors='coerce')
    if not audit_df.empty:
        audit_df['Variance'] = pd.to_numeric(audit_df['Variance'], errors='coerce').fillna(0.0)
        audit_df['Date'] = pd.to_datetime(audit_df['Date'], errors='coerce')

    # Apply global timeframe masks across all data matrices
    if selected_period == 'this_month':
        if not sales_df.empty: sales_df = sales_df[(sales_df['Sale_Date'].dt.year == current_year) & (sales_df['Sale_Date'].dt.month == current_month)]
        if not expenses_df.empty: expenses_df = expenses_df[(expenses_df['Expense_Date'].dt.year == current_year) & (expenses_df['Expense_Date'].dt.month == current_month)]
        if not audit_df.empty: audit_df = audit_df[(audit_df['Date'].dt.year == current_year) & (audit_df['Date'].dt.month == current_month)]
    elif selected_period == 'last_month':
        last_month = 12 if current_month == 1 else current_month - 1
        last_year = current_year - 1 if current_month == 1 else current_year
        if not sales_df.empty: sales_df = sales_df[(sales_df['Sale_Date'].dt.year == last_year) & (sales_df['Sale_Date'].dt.month == last_month)]
        if not expenses_df.empty: expenses_df = expenses_df[(expenses_df['Expense_Date'].dt.year == last_year) & (expenses_df['Expense_Date'].dt.month == last_month)]
        if not audit_df.empty: audit_df = audit_df[(audit_df['Date'].dt.year == last_year) & (audit_df['Date'].dt.month == last_month)]

    # 💰 CORE REVENUE & COST OF GOODS SOLD (COGS) CALCULATIONS
    total_revenue = 0.0
    total_cogs = 0.0
    total_sales_count = 0
    
    if not sales_df.empty:
        total_revenue = float(sales_df['Total_Amount'].sum())
        total_sales_count = len(sales_df)
        if not products_df.empty:
            for _, sale_row in sales_df.iterrows():
                p_id = sale_row['Product_ID']
                qty_sold = float(sale_row['Quantity'])
                prod_match = products_df[products_df['Product_ID'] == p_id]
                if not prod_match.empty:
                    unit_cost = float(pd.to_numeric(prod_match['Cost_Price'], errors='coerce').fillna(0.0).iloc[0])
                    total_cogs += (qty_sold * unit_cost)

    # 🏢 OPERATING EXPENSES (FIXED OVERHEAD)
    total_expenses = float(expenses_df['Amount'].sum()) if not expenses_df.empty else 0.0

    # 🔄 RECONCILIATION FOR KITCHEN WASTE LOSS VALUES
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

    # 📋 FINANCIAL STATEMENTS MATRIX MATH
    gross_profit_margin = total_revenue - total_cogs
    net_profit = gross_profit_margin - total_expenses - total_waste_cost

    # Warehouse Material Inventory asset valuation
    warehouse_asset_value = 0.0
    if not ingredients_df.empty:
        ingredients_df['Current_Stock'] = pd.to_numeric(ingredients_df['Current_Stock'], errors='coerce').fillna(0.0)
        ingredients_df['Cost_Per_Unit'] = pd.to_numeric(ingredients_df['Cost_Per_Unit'], errors='coerce').fillna(0.0)
        warehouse_asset_value = float((ingredients_df['Current_Stock'] * ingredients_df['Cost_Per_Unit']).sum())

    # Balance Sheet Equations Formulas
    total_assets = net_profit + warehouse_asset_value
    total_liabilities = 0.0  
    owners_equity = total_assets - total_liabilities

    # ==========================================
    # 📈 BREAK-EVEN ANALYSIS CALCULATOR ENGINE
    # ==========================================
    if total_revenue > 0:
        gross_margin_pct = (gross_profit_margin / total_revenue) * 100.0
    elif not products_df.empty:
        # Fallback to average menu item margin %
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

    # Ensure valid positive percent threshold
    if gross_margin_pct <= 0:
        gross_margin_pct = 65.0

    # Period Break-Even Target Calculation
    if total_expenses > 0 and gross_margin_pct > 0:
        break_even_target = total_expenses / (gross_margin_pct / 100.0)
    else:
        break_even_target = 0.0

    daily_break_even = break_even_target / 30.0

    # Average Order Value (AOV) & Ticket Calculations
    if total_sales_count > 0 and total_revenue > 0:
        aov = total_revenue / total_sales_count
    else:
        aov = 150.0  # Standard F&B ticket fallback benchmark

    daily_tickets_needed = int(round(daily_break_even / aov)) if aov > 0 else 0

    # Status Zone & Progress Calculations
    if break_even_target > 0:
        bep_progress_pct = min(100.0, (total_revenue / break_even_target) * 100.0)
    else:
        bep_progress_pct = 0.0

    if total_revenue >= break_even_target and break_even_target > 0:
        bep_status_text = "PROFIT ZONE 🟢"
        bep_status_desc = f"Revenue exceeds fixed operating costs by ₱{total_revenue - break_even_target:,.2f}."
        bep_status_color = "#10b981"
        bep_badge_class = "bg-success"
    elif total_revenue >= (break_even_target * 0.8) and break_even_target > 0:
        bep_status_text = "CAUTION ZONE 🟡"
        bep_status_desc = f"You need ₱{break_even_target - total_revenue:,.2f} more in gross sales to reach break-even."
        bep_status_color = "#f59e0b"
        bep_badge_class = "bg-warning text-dark"
    else:
        bep_status_text = "LOSS ZONE 🔴"
        needed = break_even_target - total_revenue
        bep_status_desc = f"Current revenue is ₱{needed:,.2f} short of covering operating overhead." if break_even_target > 0 else "Log operating expenses and products to calculate your break-even threshold."
        bep_status_color = "#ef4444"
        bep_badge_class = "bg-danger"

    # 🎯 MENU ENGINEERING MATRIX ALGORITHM DATA COMPILER
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
                    action_notes.append(f"💡 <strong>Plowhorse Alert:</strong> '{p['name']}' generates high sales volume but thin margins. Re-evaluate ingredient portions or optimize vendor sourcing costs.")
                elif quadrant == 'Puzzles':
                    action_notes.append(f"🎯 <strong>Puzzle Opportunity:</strong> '{p['name']}' has strong gross profitability but slow sales movement. Feature prominently or tie into promotional bundles.")
                    
            menu_data_json = json.dumps(chart_points)

    # FETCH SALES DATA ACTIVITY LOG
    recent_sales = []
    if not sales_df.empty:
        sales_sorted = sales_df.sort_values('Sale_Date', ascending=False).head(8)
        for _, row in sales_sorted.iterrows():
            p_id = row['Product_ID']
            p_name = products_df[products_df['Product_ID'] == p_id]['Product_Name'].values[0] if not products_df.empty and p_id in products_df['Product_ID'].values else p_id
            date_str = row['Sale_Date'].strftime("%Y-%m-%d") if pd.notnull(row['Sale_Date']) else datetime.now().strftime("%Y-%m-%d")
            recent_sales.append({
                'Sale_Date': date_str, 'Sale_Time': str(row.get('Sale_Time', '')),
                'Product_Name': p_name, 'Quantity': float(row['Quantity']), 'Total_Amount': float(row['Total_Amount'])
            })

    # FETCH HR ENTRIES
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
        menu_data_json=menu_data_json,
        avg_qty=avg_qty_threshold,
        avg_margin=avg_margin_threshold,
        quadrants=quadrant_counts,
        advice=action_notes[:4],
        msg=feedback_msg,
        alert_type=alert_type,
        now=now,
        # BREAK-EVEN ANALYTICS CONTEXT
        gross_margin_pct=gross_margin_pct,
        break_even_target=break_even_target,
        daily_break_even=daily_break_even,
        aov=aov,
        daily_tickets_needed=daily_tickets_needed,
        bep_progress_pct=bep_progress_pct,
        bep_status_text=bep_status_text,
        bep_status_desc=bep_status_desc,
        bep_status_color=bep_status_color,
        bep_badge_class=bep_badge_class
    )