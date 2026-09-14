# routes/corrections.py - Secure Voids and Corrections Module
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd
import sqlite3
from datetime import datetime
import io

corrections_bp = Blueprint('corrections', __name__)

@corrections_bp.route('/portal/<username>/corrections', methods=['GET', 'POST'])
def web_corrections_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    staff_role = session.get('staff_role', 'Staff')
    
    if staff_role not in ['Platform Owner Admin', 'Store Manager']:
        return redirect(f"/portal/{username}/sales?error=Security Block: Only Managers and Admins can access the Corrections module.")

    db_path = f"data/client_{username}.db"
    client_db = InventoryDB(db_path)
    feedback_msg = None
    alert_type = "success"

    if request.method == 'POST':
        action = request.form.get('action_type')
        operator = session.get('logged_in_user', 'System')
        
        # SALES VOID PROCESSING (SUPPORTS BOTH FINISHED PRODUCTS & MODIFIERS)
        if action == 'void_sale':
            sale_id = request.form.get('sale_id', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            
            if not sale_id or not void_reason:
                return redirect(f"/portal/{username}/corrections?error=Compliance Violation: Sale ID and Void Reason are strictly required.")
                
            try:
                conn = sqlite3.connect(db_path, timeout=20.0)
                cursor = conn.cursor()
                
                # Fetch original sale record
                cursor.execute("""
                    SELECT Product_ID, Product_Name, Quantity, Price, Total_Amount, Sale_Date 
                    FROM Sales 
                    WHERE Sale_ID = ?
                """, (sale_id,))
                sale_record = cursor.fetchone()
                
                if not sale_record:
                    conn.close()
                    return redirect(f"/portal/{username}/corrections?error=Database Error: Sale ID {sale_id} not found.")
                    
                p_id, p_name, original_qty, price, original_amt, original_sale_date = sale_record
                p_name = p_name or p_id
                original_qty = float(original_qty or 0.0)
                price = float(price or 0.0)
                original_amt = float(original_amt or 0.0)

                system_time_exact = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                void_sale_id = f"VOID-{sale_id}"
                
                cursor.execute("SELECT COUNT(*) FROM Sales WHERE Sale_ID = ?", (void_sale_id,))
                if cursor.fetchone()[0] > 0:
                    conn.close()
                    return redirect(f"/portal/{username}/corrections?error=Duplicate Action: This transaction has already been voided.")

                # Insert offsetting negative void record into Sales
                cursor.execute("""
                    INSERT INTO Sales (Sale_ID, Sale_Date, Sale_Time, Product_ID, Product_Name, Quantity, Price, Total_Amount, Reason, Recorded_By)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    void_sale_id, 
                    original_sale_date, 
                    datetime.now().strftime("%H:%M:%S"), 
                    p_id, 
                    f"[VOID] {p_name}", 
                    -original_qty, 
                    price, 
                    -original_amt, 
                    f"[VOIDED] Reason: {void_reason}", 
                    operator
                ))

                # RESTOCK DEDUCTED INGREDIENTS (AUTOMATICALLY HANDLES BOTH PRODUCTS AND MODIFIERS)
                restocked_summary = []

                # 1. Check Modifier_Recipes (for Modifiers like Extra Espresso Shot, Oat Milk)
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifier_Recipes'")
                if cursor.fetchone():
                    cursor.execute("SELECT Ingredient_ID, Quantity_Required, Unit FROM Modifier_Recipes WHERE Modifier_ID = ?", (p_id,))
                    mod_recipe_rows = cursor.fetchall()
                    for ing_id, req_qty, rec_unit in mod_recipe_rows:
                        tot_refund = float(req_qty or 0.0) * original_qty
                        cursor.execute("SELECT Current_Stock, Ingredient_Name, Unit FROM Ingredients WHERE Ingredient_ID = ?", (ing_id,))
                        ing_match = cursor.fetchone()
                        if ing_match:
                            current_stock, ing_name, base_unit = ing_match
                            current_stock = float(current_stock or 0.0)
                            new_stock = current_stock + tot_refund
                            cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_stock, ing_id))
                            cursor.execute("""
                                INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                void_sale_id, 
                                system_time_exact, 
                                ing_name, 
                                current_stock, 
                                new_stock, 
                                tot_refund, 
                                f"VOID RESTORE: {original_qty:g}x Modifier ({p_name}) | Reason: {void_reason}"
                            ))
                            restocked_summary.append(f"{tot_refund:g} {base_unit or ''} {ing_name}".strip())

                # 2. Check Standard Product Recipes
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Recipes'")
                if cursor.fetchone():
                    cursor.execute("SELECT Ingredient_ID, Quantity_Required, Unit FROM Recipes WHERE Product_ID = ?", (p_id,))
                    prod_recipe_rows = cursor.fetchall()
                    for ing_id, req_qty, rec_unit in prod_recipe_rows:
                        tot_refund = float(req_qty or 0.0) * original_qty
                        cursor.execute("SELECT Current_Stock, Ingredient_Name, Unit FROM Ingredients WHERE Ingredient_ID = ?", (ing_id,))
                        ing_match = cursor.fetchone()
                        if ing_match:
                            current_stock, ing_name, base_unit = ing_match
                            current_stock = float(current_stock or 0.0)
                            new_stock = current_stock + tot_refund
                            cursor.execute("UPDATE Ingredients SET Current_Stock = ? WHERE Ingredient_ID = ?", (new_stock, ing_id))
                            cursor.execute("""
                                INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Theoretical, Physical, Variance, Notes)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                void_sale_id, 
                                system_time_exact, 
                                ing_name, 
                                current_stock, 
                                new_stock, 
                                tot_refund, 
                                f"VOID RESTORE: {original_qty:g}x Product ({p_name}) | Reason: {void_reason}"
                            ))
                            restocked_summary.append(f"{tot_refund:g} {base_unit or ''} {ing_name}".strip())

                conn.commit()
                conn.close()

                client_db.update_all_product_costs()

                if restocked_summary:
                    feedback_msg = f"Success: Sale {sale_id} voided. Restored to inventory: {', '.join(restocked_summary)}."
                else:
                    feedback_msg = f"Success: Sale {sale_id} voided. Financial ledger updated."
                alert_type = "success"

            except Exception as e:
                feedback_msg = f"Error processing void: {str(e)}"
                alert_type = "danger"

        # WASTAGE VOID PROCESSING
        elif action == 'void_waste':
            waste_id = request.form.get('waste_id', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            
            if not waste_id or not void_reason:
                return redirect(f"/portal/{username}/corrections?error=Compliance Violation: Waste Audit ID and Void Reason are strictly required.")
            
            try:
                audit_df = client_db.read_tab('Inventory_Audit_Log')
                if audit_df is None or audit_df.empty:
                    return redirect(f"/portal/{username}/corrections?error=Database Error: Audit log is empty.")
                
                target_idx = audit_df.index[audit_df['Audit_ID'] == waste_id].tolist()
                if not target_idx:
                    return redirect(f"/portal/{username}/corrections?error=Database Error: Waste record {waste_id} not found.")
                
                idx = target_idx[0]
                
                if "[VOIDED]" in str(audit_df.at[idx, 'Notes']):
                    return redirect(f"/portal/{username}/corrections?error=Duplicate Action: This wastage entry has already been voided.")
                    
                item_target = str(audit_df.at[idx, 'Ingredient_Name'])
                original_variance = float(audit_df.at[idx, 'Variance'])
                
                refund_qty = abs(original_variance)
                
                conn = sqlite3.connect(db_path, timeout=20.0)
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(Ingredients)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'Current_Stock' in cols:
                    cursor.execute("UPDATE Ingredients SET Current_Stock = Current_Stock + ? WHERE Ingredient_Name = ? OR Ingredient_ID = ?", (refund_qty, item_target, item_target))
                conn.commit()
                conn.close()
                
                original_notes = str(audit_df.at[idx, 'Notes'])
                audit_df.at[idx, 'Variance'] = 0.0
                audit_df.at[idx, 'Notes'] = f"[VOIDED] {original_notes} | Auth: {operator} | Reason: {void_reason}"
                
                client_db.save_tab('Inventory_Audit_Log', audit_df)
                
                feedback_msg = f"Success: Waste entry {waste_id} neutralized. Inventory restored and financial reports updated."
                alert_type = "success"
                
            except Exception as e:
                feedback_msg = f"Error processing waste void: {str(e)}"
                alert_type = "danger"

        # STOCK INTAKE VOID PROCESSING
        elif action == 'void_intake':
            intake_id = request.form.get('intake_id', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            
            if not intake_id or not void_reason:
                return redirect(f"/portal/{username}/corrections?error=Compliance Violation: Intake Audit ID and Void Reason are strictly required.")
            
            try:
                audit_df = client_db.read_tab('Inventory_Audit_Log')
                if audit_df is None or audit_df.empty:
                    return redirect(f"/portal/{username}/corrections?error=Database Error: Audit log is empty.")
                
                target_idx = audit_df.index[audit_df['Audit_ID'] == intake_id].tolist()
                if not target_idx:
                    return redirect(f"/portal/{username}/corrections?error=Database Error: Intake record {intake_id} not found.")
                
                idx = target_idx[0]
                
                if "[VOIDED]" in str(audit_df.at[idx, 'Notes']):
                    return redirect(f"/portal/{username}/corrections?error=Duplicate Action: This intake entry has already been voided.")
                    
                item_target = str(audit_df.at[idx, 'Ingredient_Name'])
                original_variance = float(audit_df.at[idx, 'Variance'])
                
                deduct_qty = abs(original_variance)
                
                # Reverse the intake (subtract from current stock)
                conn = sqlite3.connect(db_path, timeout=20.0)
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(Ingredients)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'Current_Stock' in cols:
                    cursor.execute("UPDATE Ingredients SET Current_Stock = Current_Stock - ? WHERE Ingredient_Name = ? OR Ingredient_ID = ?", (deduct_qty, item_target, item_target))
                conn.commit()
                conn.close()
                
                original_notes = str(audit_df.at[idx, 'Notes'])
                audit_df.at[idx, 'Variance'] = 0.0
                audit_df.at[idx, 'Notes'] = f"[VOIDED] {original_notes} | Auth: {operator} | Reason: {void_reason}"
                
                client_db.save_tab('Inventory_Audit_Log', audit_df)
                
                feedback_msg = f"Success: Intake entry {intake_id} neutralized. Overstated inventory has been successfully deducted."
                alert_type = "success"
                
            except Exception as e:
                feedback_msg = f"Error processing intake void: {str(e)}"
                alert_type = "danger"

        # EXPENSE VOID PROCESSING
        elif action == 'void_expense':
            expense_rowid = request.form.get('expense_rowid', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            
            if not expense_rowid or not void_reason:
                return redirect(f"/portal/{username}/corrections?error=Compliance Violation: Expense ID and Void Reason are strictly required.")
            
            try:
                conn = sqlite3.connect(db_path, timeout=20.0)
                cursor = conn.cursor()
                
                cursor.execute("SELECT Amount, Description FROM Expenses WHERE rowid = ?", (expense_rowid,))
                expense_record = cursor.fetchone()
                
                if not expense_record:
                    conn.close()
                    return redirect(f"/portal/{username}/corrections?error=Database Error: Expense record not found.")
                
                original_desc = str(expense_record[1])
                if "[VOIDED]" in original_desc:
                    conn.close()
                    return redirect(f"/portal/{username}/corrections?error=Duplicate Action: This expense has already been voided.")
                
                new_desc = f"[VOIDED] {original_desc} | Auth: {operator} | Reason: {void_reason}"
                
                cursor.execute("UPDATE Expenses SET Amount = 0.0, Description = ? WHERE rowid = ?", (new_desc, expense_rowid))
                conn.commit()
                conn.close()
                
                feedback_msg = f"Success: Expense log neutralized. The financial ledger has been updated."
                alert_type = "success"
                
            except Exception as e:
                feedback_msg = f"Error processing expense void: {str(e)}"
                alert_type = "danger"

        return redirect(f"/portal/{username}/corrections?msg={feedback_msg}&alert_type={alert_type}")

    # FETCH SALES FOR UI
    sales_df = client_db.read_tab('Sales')
    recent_sales = []
    if not sales_df.empty:
        void_records = sales_df[sales_df['Sale_ID'].astype(str).str.startswith('VOID-', na=False)]
        voided_ids = set([str(vid).replace('VOID-', '') for vid in void_records['Sale_ID'].tolist()])
        valid_sales = sales_df[~sales_df['Sale_ID'].astype(str).str.startswith('VOID', na=False)]
        
        if 'Sale_Date' in valid_sales.columns and 'Sale_Time' in valid_sales.columns:
            valid_sales = valid_sales.sort_values(['Sale_Date', 'Sale_Time'], ascending=[False, False])
        elif 'System_Timestamp' in valid_sales.columns:
            valid_sales = valid_sales.sort_values('System_Timestamp', ascending=False)
        else:
            valid_sales = valid_sales.sort_values('Sale_ID', ascending=False)
            
        recent_sales_raw = valid_sales.head(100).to_dict(orient='records')
        for sale in recent_sales_raw:
            sale['is_voided'] = sale['Sale_ID'] in voided_ids
            recent_sales.append(sale)
            
    # FETCH AUDIT LOGS FOR UI (WASTE AND INTAKE)
    audit_df = client_db.read_tab('Inventory_Audit_Log')
    recent_waste = []
    recent_intake = []
    
    if audit_df is not None and not audit_df.empty:
        if 'Date' in audit_df.columns:
            audit_df = audit_df.sort_values('Date', ascending=False)
            
        # Parse Waste
        waste_mask = audit_df['Audit_ID'].astype(str).str.startswith('WST', na=False) | audit_df['Notes'].astype(str).str.contains('Waste|Spoil', case=False, na=False)
        valid_waste = audit_df[waste_mask].head(100).to_dict(orient='records')
        for waste in valid_waste:
            waste['is_voided'] = '[VOIDED]' in str(waste.get('Notes', ''))
            recent_waste.append(waste)
            
        # Parse Intake
        intake_mask = audit_df['Audit_ID'].astype(str).str.startswith('RCV', na=False) | audit_df['Audit_ID'].astype(str).str.startswith('AUD', na=False)
        valid_intake = audit_df[intake_mask].head(100).to_dict(orient='records')
        for intake in valid_intake:
            intake['is_voided'] = '[VOIDED]' in str(intake.get('Notes', ''))
            recent_intake.append(intake)

    # FETCH EXPENSES FOR UI
    recent_expenses = []
    try:
        conn = sqlite3.connect(db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT rowid, * FROM Expenses ORDER BY rowid DESC LIMIT 100")
        expense_rows = cursor.fetchall()
        for row in expense_rows:
            exp = dict(row)
            exp['is_voided'] = '[VOIDED]' in str(exp.get('Description', ''))
            recent_expenses.append(exp)
        conn.close()
    except Exception:
        pass

    server_error = request.args.get('error', '')
    if server_error:
        feedback_msg = server_error
        alert_type = "danger"

    return render_template(
        'corrections.html',
        username=username,
        recent_sales=recent_sales,
        recent_waste=recent_waste,
        recent_intake=recent_intake,
        recent_expenses=recent_expenses,
        msg=request.args.get('msg', feedback_msg),
        alert_type=request.args.get('alert_type', alert_type)
    )