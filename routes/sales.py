# routes/sales.py - End-of-Day (EOD) Sales Entry & Recipe Inventory Deduction Engine
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
    
    # 1. Respect explicit database values if populated
    if raw_parent and str(raw_parent).strip().lower() not in ['nan', 'none', '', 'null']:
        parent = str(raw_parent).strip()
        variant = str(raw_variant).strip() if (raw_variant and str(raw_variant).strip().lower() not in ['nan', 'none', '', 'null']) else 'Regular'
        return parent, variant

    full_name = str(p.get('Product_Name') or '').strip()
    
    # 2. Match Prefix Patterns: "Hot - Brown Sugar Coffee", "Iced- Americano Coffee", "Hot Cafe Mocha"
    prefix_match = re.match(r"^(Hot|Iced|Cold|Warm)\s*[-–—:]?\s*(.+)$", full_name, re.IGNORECASE)
    if prefix_match:
        variant = prefix_match.group(1).strip().capitalize()
        parent = prefix_match.group(2).strip()
        return parent, variant

    # 3. Match Suffix Patterns: "Brown Sugar Coffee - Hot", "Americano (Iced)"
    suffix_match = re.match(r"^(.+?)\s*[-–—:(]\s*(Hot|Iced|Cold|Warm|12oz|16oz|22oz|Regular|Large)\)?$", full_name, re.IGNORECASE)
    if suffix_match:
        parent = suffix_match.group(1).strip()
        variant = suffix_match.group(2).strip().capitalize()
        return parent, variant

    # 4. Standard Delimiter: "Product Family - Variant"
    delimiter_match = re.match(r"^([^-–—(]+)\s*[-–—]\s*(.+)$", full_name)
    if delimiter_match:
        part1 = delimiter_match.group(1).strip()
        part2 = delimiter_match.group(2).strip()
        if part1.lower() in ['hot', 'iced', 'cold', 'warm']:
            return part2, part1.capitalize()
        return part1, part2

    return full_name, "Regular"

@sales_bp.route('/portal/<username>/sales', methods=['GET', 'POST'])
def web_sales_tab(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username:
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    feedback_msg = None
    alert_type = "success"

    # ==========================================
    # 1. POST METHOD: SUBMIT EOD CLOSING SALES
    # ==========================================
    if request.method == 'POST':
        sale_date = request.form.get('sale_date', '').strip() or datetime.now().strftime("%Y-%m-%d")
        audit_note = request.form.get('audit_note', '').strip()
        recorded_by = session.get('staff_role') or session.get('logged_in_user') or 'Staff'
        
        prod_ids = request.form.getlist('product_id[]')
        prod_qtys = request.form.getlist('quantity[]')
        
        mod_ids = request.form.getlist('modifier_id[]')
        mod_qtys = request.form.getlist('modifier_quantity[]')
        
        conn = sqlite3.connect(client_db_path, timeout=20.0)
        cursor = conn.cursor()
        
        # Ensure Sales and Audit tables exist
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

        logged_sales_count = 0
        sale_time_str = datetime.now().strftime("%H:%M:%S")

        # Process Products Sold
        for p_id, q_str in zip(prod_ids, prod_qtys):
            try:
                qty = float(q_str or 0)
            except (ValueError, TypeError):
                qty = 0.0
                
            if qty == 0:
                continue

            cursor.execute("SELECT Product_Name, Selling_Price FROM Products WHERE Product_ID = ?", (p_id,))
            prod_match = cursor.fetchone()
            p_name = prod_match[0] if prod_match else p_id
            selling_price = float(prod_match[1] or 0.0) if prod_match else 0.0
            line_total = qty * selling_price
            
            sale_tx_id = f"SAL{datetime.now().strftime('%M%S')}{logged_sales_count:02d}"

            cursor.execute("""
                INSERT INTO Sales (
                    Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name,
                    Quantity, Price, Total_Amount, Reason, Recorded_By
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sale_tx_id, sale_date, sale_time_str, p_id, p_name, qty, selling_price, line_total, audit_note, recorded_by))

            # Deduct ingredient inventory according to recipe specifications
            cursor.execute("SELECT Ingredient_ID, Quantity_Required, Unit FROM Recipes WHERE Product_ID = ?", (p_id,))
            recipe_rows = cursor.fetchall()

            for ing_id, req_qty, rec_unit in recipe_rows:
                tot_deduct = float(req_qty or 0.0) * qty
                cursor.execute("SELECT Current_Stock, Ingredient_Name, Unit FROM Ingredients WHERE Ingredient_ID = ?", (ing_id,))
                ing_match = cursor.fetchone()

                if ing_match:
                    current_stock, ing_name, base_unit = ing_match
                    current_stock = float(current_stock or 0.0)
                    new_stock = current_stock - tot_deduct

                    cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_stock, ing_id))
                    
                    cursor.execute("""
                        INSERT INTO Inventory_Audit_Log (
                            Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        sale_tx_id, 
                        sale_date, 
                        ing_name, 
                        current_stock, 
                        new_stock, 
                        -tot_deduct, 
                        f"POS Depletion: {qty:g}x {p_name} | {audit_note}".strip(" | ")
                    ))

            logged_sales_count += 1

        # Process Modifiers Sold
        for m_id, mq_str in zip(mod_ids, mod_qtys):
            try:
                m_qty = float(mq_str or 0)
            except (ValueError, TypeError):
                m_qty = 0.0
                
            if m_qty == 0:
                continue

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifiers'")
            if cursor.fetchone():
                cursor.execute("SELECT Modifier_Name, Price FROM Modifiers WHERE Modifier_ID = ?", (m_id,))
                mod_match = cursor.fetchone()
                m_name = mod_match[0] if mod_match else m_id
                m_price = float(mod_match[1] or 0.0) if mod_match else 0.0
                m_total = m_qty * m_price
                
                mod_tx_id = f"MOD{datetime.now().strftime('%M%S')}{logged_sales_count:02d}"

                cursor.execute("""
                    INSERT INTO Sales (
                        Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name,
                        Quantity, Price, Total_Amount, Reason, Recorded_By
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (mod_tx_id, sale_date, sale_time_str, m_id, f"Modifier: {m_name}", m_qty, m_price, m_total, audit_note, recorded_by))
                logged_sales_count += 1

        conn.commit()
        conn.close()
        client_db.update_all_product_costs()

        return redirect(f"/portal/{username}/sales?msg=Success:+Successfully+recorded+closing+sales+and+deducted+recipe+ingredients.&alert_type=success")

    # ==========================================
    # 2. GET METHOD: RENDER GROUPED WORKSHEET
    # ==========================================
    conn = sqlite3.connect(client_db_path, timeout=20.0)
    
    # Read active products and build parent-variant dictionary
    products_df = pd.read_sql("SELECT * FROM Products WHERE Active = 'Yes' OR Active = 'yes'", conn)
    
    grouped_products = defaultdict(list)
    categories = []
    
    if not products_df.empty:
        categories = sorted(list(set(str(c).strip() for c in products_df['Category'].dropna() if str(c).strip())))
        
        for _, p in products_df.iterrows():
            parent_name, variant_name = resolve_parent_and_variant(p)
            
            p_obj = {
                'Product_ID': str(p['Product_ID']),
                'Product_Name': str(p['Product_Name']),
                'Parent_Item': parent_name,
                'Variant_Name': variant_name,
                'Category': str(p.get('Category') or 'General'),
                'Selling_Price': float(pd.to_numeric(p.get('Selling_Price', 0.0), errors='coerce') or 0.0)
            }
            grouped_products[parent_name].append(p_obj)

    # Read active modifiers
    active_modifiers = []
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifiers'")
    if cursor.fetchone():
        mods_df = pd.read_sql("SELECT * FROM Modifiers WHERE Active = 'Yes' OR Active = 'yes'", conn)
        if not mods_df.empty:
            active_modifiers = mods_df.to_dict('records')

    # Read historical sales grouped by date
    sales_history = []
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Sales'")
    if cursor.fetchone():
        sales_ledger_df = pd.read_sql("SELECT * FROM Sales ORDER BY Sale_Date DESC, Sale_Time DESC", conn)
        
        if not sales_ledger_df.empty:
            sales_ledger_df['Sale_Date'] = sales_ledger_df['Sale_Date'].astype(str)
            unique_dates = sales_ledger_df['Sale_Date'].unique()

            for u_date in unique_dates:
                day_entries = sales_ledger_df[sales_ledger_df['Sale_Date'] == u_date]
                total_qty = float(pd.to_numeric(day_entries['Quantity'], errors='coerce').fillna(0.0).sum())
                total_revenue = float(pd.to_numeric(day_entries['Total_Amount'], errors='coerce').fillna(0.0).sum())

                sales_history.append({
                    'date': u_date,
                    'total_qty': total_qty,
                    'total_revenue': total_revenue,
                    'entries': day_entries.to_dict('records')
                })

    conn.close()

    return render_template(
        'sales.html',
        username=username,
        grouped_products=grouped_products,
        categories=categories,
        active_modifiers=active_modifiers,
        sales_history=sales_history,
        msg=request.args.get('msg', feedback_msg),
        alert_type=request.args.get('alert_type', alert_type)
    )