# routes/corrections.py - Secure Voids and Corrections Module
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import sqlite3
from datetime import datetime
import urllib.parse

corrections_bp = Blueprint('corrections', __name__)

def _get_table_columns(cursor, table_name):
    """Retrieve column names for an existing SQLite table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [col[1] for col in cursor.fetchall()]

@corrections_bp.route('/portal/<username>/corrections', methods=['GET', 'POST'])
def web_corrections_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    staff_role = session.get('staff_role', 'Staff')
    
    if staff_role not in ['Platform Owner Admin', 'Store Manager']:
        err_msg = urllib.parse.quote_plus("Security Block: Only Managers and Admins can access the Corrections module.")
        return redirect(f"/portal/{username}/sales?error={err_msg}")

    db_path = f"data/client_{username}.db"
    client_db = InventoryDB(db_path)
    feedback_msg = None
    alert_type = "success"

    if request.method == 'POST':
        action = request.form.get('action_type')
        operator = session.get('logged_in_user', 'System')
        system_time_exact = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_time_hms = datetime.now().strftime("%H:%M:%S")

        # ---------------------------------------------------------
        # 1. SALES VOID PROCESSING (SUPPORTS MULTI-ITEM & MODIFIERS)
        # ---------------------------------------------------------
        if action == 'void_sale':
            sale_id = request.form.get('sale_id', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            
            if not sale_id or not void_reason:
                err_msg = urllib.parse.quote_plus("Compliance Violation: Sale ID and Void Reason are strictly required.")
                return redirect(f"/portal/{username}/corrections?error={err_msg}")
                
            try:
                conn = sqlite3.connect(db_path, timeout=30.0)
                cursor = conn.cursor()
                
                # Check duplicate void
                void_sale_id = f"VOID-{sale_id}"
                cursor.execute("SELECT COUNT(*) FROM Sales WHERE Sale_ID = ?", (void_sale_id,))
                if cursor.fetchone()[0] > 0:
                    conn.close()
                    err_msg = urllib.parse.quote_plus("Duplicate Action: This transaction has already been voided.")
                    return redirect(f"/portal/{username}/corrections?error={err_msg}")

                # Fetch line items for this Sale_ID
                sales_cols = _get_table_columns(cursor, "Sales")
                cursor.execute("SELECT * FROM Sales WHERE Sale_ID = ?", (sale_id,))
                sale_rows = cursor.fetchall()
                
                if not sale_rows:
                    conn.close()
                    err_msg = urllib.parse.quote_plus(f"Database Error: Sale ID {sale_id} not found.")
                    return redirect(f"/portal/{username}/corrections?error={err_msg}")

                col_idx = {col: i for i, col in enumerate(sales_cols)}
                restocked_summary = []

                for row in sale_rows:
                    p_id = row[col_idx['Product_ID']] if 'Product_ID' in col_idx else None
                    p_name = row[col_idx['Product_Name']] if 'Product_Name' in col_idx else p_id
                    original_qty = float(row[col_idx['Quantity']] or 0.0) if 'Quantity' in col_idx else 0.0
                    price = float(row[col_idx['Price']] or 0.0) if 'Price' in col_idx else 0.0
                    original_amt = float(row[col_idx['Total_Amount']] or 0.0) if 'Total_Amount' in col_idx else 0.0
                    original_sale_date = row[col_idx['Sale_Date']] if 'Sale_Date' in col_idx else datetime.now().strftime("%Y-%m-%d")

                    insert_cols = ['Sale_ID', 'Sale_Date', 'Sale_Time', 'Product_ID', 'Product_Name', 'Quantity', 'Price', 'Total_Amount']
                    insert_vals = [
                        void_sale_id,
                        original_sale_date,
                        current_time_hms,
                        p_id,
                        f"[VOID] {p_name}",
                        -original_qty,
                        price,
                        -original_amt
                    ]

                    if 'Reason' in col_idx:
                        insert_cols.append('Reason')
                        insert_vals.append(f"[VOIDED] {void_reason}")
                    if 'Recorded_By' in col_idx:
                        insert_cols.append('Recorded_By')
                        insert_vals.append(operator)

                    placeholders = ', '.join(['?'] * len(insert_vals))
                    columns_sql = ', '.join(insert_cols)
                    cursor.execute(f"INSERT INTO Sales ({columns_sql}) VALUES ({placeholders})", insert_vals)

                    # Restock Ingredients: Modifiers
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Modifier_Recipes'")
                    if cursor.fetchone():
                        cursor.execute("SELECT Ingredient_ID, Quantity_Required, Unit FROM Modifier_Recipes WHERE Modifier_ID = ?", (p_id,))
                        for ing_id, req_qty, rec_unit in cursor.fetchall():
                            tot_refund = float(req_qty or 0.0) * original_qty
                            cursor.execute("UPDATE Ingredients SET Current_Stock = Current_Stock + ? WHERE Ingredient_ID = ?", (tot_refund, ing_id))
                            
                            cursor.execute("SELECT Ingredient_Name, Unit FROM Ingredients WHERE Ingredient_ID = ?", (ing_id,))
                            ing_info = cursor.fetchone()
                            ing_name = ing_info[0] if ing_info else ing_id
                            base_unit = ing_info[1] if ing_info else (rec_unit or '')
                            
                            cursor.execute("""
                                INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Variance, Notes)
                                VALUES (?, ?, ?, ?, ?)
                            """, (
                                void_sale_id,
                                system_time_exact,
                                ing_name,
                                tot_refund,
                                f"VOID RESTORE: {original_qty:g}x Modifier ({p_name}) | Auth: {operator} | Reason: {void_reason}"
                            ))
                            restocked_summary.append(f"{tot_refund:g} {base_unit} {ing_name}".strip())

                    # Restock Ingredients: Standard Recipes
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Recipes'")
                    if cursor.fetchone():
                        cursor.execute("SELECT Ingredient_ID, Quantity_Required, Unit FROM Recipes WHERE Product_ID = ?", (p_id,))
                        for ing_id, req_qty, rec_unit in cursor.fetchall():
                            tot_refund = float(req_qty or 0.0) * original_qty
                            cursor.execute("UPDATE Ingredients SET Current_Stock = Current_Stock + ? WHERE Ingredient_ID = ?", (tot_refund, ing_id))
                            
                            cursor.execute("SELECT Ingredient_Name, Unit FROM Ingredients WHERE Ingredient_ID = ?", (ing_id,))
                            ing_info = cursor.fetchone()
                            ing_name = ing_info[0] if ing_info else ing_id
                            base_unit = ing_info[1] if ing_info else (rec_unit or '')
                            
                            cursor.execute("""
                                INSERT INTO Inventory_Audit_Log (Audit_ID, Date, Ingredient_Name, Variance, Notes)
                                VALUES (?, ?, ?, ?, ?)
                            """, (
                                void_sale_id,
                                system_time_exact,
                                ing_name,
                                tot_refund,
                                f"VOID RESTORE: {original_qty:g}x Product ({p_name}) | Auth: {operator} | Reason: {void_reason}"
                            ))
                            restocked_summary.append(f"{tot_refund:g} {base_unit} {ing_name}".strip())

                # Check if the entire EOD batch is now voided and neutralize its Cash_Drawer_Logs and auto-expenses
                clean_batch_id = sale_id.replace('VOID-', '').split('-')[0] if '-' in sale_id else sale_id.replace('VOID-', '')
                cursor.execute("""
                    SELECT COUNT(*) FROM Sales 
                    WHERE (Sale_ID LIKE ? OR Sale_ID = ?) 
                      AND Sale_ID NOT LIKE 'VOID-%'
                      AND Sale_ID NOT IN (SELECT REPLACE(Sale_ID, 'VOID-', '') FROM Sales WHERE Sale_ID LIKE 'VOID-%')
                """, (f"{clean_batch_id}-%", clean_batch_id))
                remaining_active = cursor.fetchone()[0]

                if remaining_active == 0:
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Cash_Drawer_Logs'")
                    if cursor.fetchone():
                        cursor.execute("""
                            UPDATE Cash_Drawer_Logs
                            SET Starting_Float = 0.0, Cash_Sales = 0.0, Cash_Paid_Outs = 0.0,
                                Expected_Cash = 0.0, Actual_Counted_Cash = 0.0, Discrepancy_Over_Short = 0.0,
                                GCash_Sales = 0.0, Maya_Sales = 0.0, Card_Sales = 0.0,
                                Grab_Gross = 0.0, Grab_Commission = 0.0, Grab_Net = 0.0,
                                Foodpanda_Gross = 0.0, Foodpanda_Commission = 0.0, Foodpanda_Net = 0.0,
                                Total_Settled_Tenders = 0.0, Tender_Variance = 0.0,
                                Explanation_Notes = '[VOIDED] ' || coalesce(Explanation_Notes, '')
                            WHERE Batch_ID = ? OR Drawer_Tx_ID LIKE ?
                        """, (clean_batch_id, f"{clean_batch_id}%"))
                    
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Expenses'")
                    if cursor.fetchone():
                        cursor.execute("""
                            UPDATE Expenses
                            SET Amount = 0.0, Description = '[VOIDED] ' || Description
                            WHERE Expense_ID LIKE ? AND Description NOT LIKE '[VOIDED]%'
                        """, (f"%{clean_batch_id}%",))

                conn.commit()
                conn.close()

                try:
                    client_db.update_all_product_costs()
                except Exception:
                    pass

                summary_txt = f" Restored: {', '.join(set(restocked_summary))}." if restocked_summary else ""
                feedback_msg = f"Success: Transaction {sale_id} voided.{summary_txt}"
                alert_type = "success"

            except Exception as e:
                feedback_msg = f"Error processing void: {str(e)}"
                alert_type = "danger"

        # ---------------------------------------------------------
        # 2. WASTAGE VOID PROCESSING (DIRECT SQL RESTOCK)
        # ---------------------------------------------------------
        elif action == 'void_waste':
            waste_id = request.form.get('waste_id', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            
            if not waste_id or not void_reason:
                err_msg = urllib.parse.quote_plus("Compliance Violation: Waste Audit ID and Void Reason are strictly required.")
                return redirect(f"/portal/{username}/corrections?error={err_msg}")
            
            try:
                conn = sqlite3.connect(db_path, timeout=30.0)
                cursor = conn.cursor()
                
                cursor.execute("SELECT Ingredient_Name, Variance, Notes FROM Inventory_Audit_Log WHERE Audit_ID = ?", (waste_id,))
                waste_row = cursor.fetchone()
                
                if not waste_row:
                    conn.close()
                    err_msg = urllib.parse.quote_plus(f"Database Error: Waste record {waste_id} not found.")
                    return redirect(f"/portal/{username}/corrections?error={err_msg}")
                
                item_name, variance, existing_notes = waste_row
                if "[VOIDED]" in str(existing_notes):
                    conn.close()
                    err_msg = urllib.parse.quote_plus("Duplicate Action: This wastage entry has already been voided.")
                    return redirect(f"/portal/{username}/corrections?error={err_msg}")
                
                refund_qty = abs(float(variance or 0.0))
                
                cursor.execute("""
                    UPDATE Ingredients 
                    SET Current_Stock = Current_Stock + ? 
                    WHERE Ingredient_Name = ? COLLATE NOCASE OR Ingredient_ID = ?
                """, (refund_qty, item_name, item_name))
                
                new_notes = f"[VOIDED] {existing_notes or ''} | Auth: {operator} | Reason: {void_reason}"
                cursor.execute("""
                    UPDATE Inventory_Audit_Log 
                    SET Variance = 0.0, Notes = ? 
                    WHERE Audit_ID = ?
                """, (new_notes, waste_id))
                
                conn.commit()
                conn.close()
                
                feedback_msg = f"Success: Waste entry {waste_id} voided. Restored {refund_qty:g} units to inventory."
                alert_type = "success"
                
            except Exception as e:
                feedback_msg = f"Error processing waste void: {str(e)}"
                alert_type = "danger"

        # ---------------------------------------------------------
        # 3. STOCK INTAKE VOID PROCESSING (DIRECT SQL DEDUCTION)
        # ---------------------------------------------------------
        elif action == 'void_intake':
            intake_id = request.form.get('intake_id', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            
            if not intake_id or not void_reason:
                err_msg = urllib.parse.quote_plus("Compliance Violation: Intake Audit ID and Void Reason are strictly required.")
                return redirect(f"/portal/{username}/corrections?error={err_msg}")
            
            try:
                conn = sqlite3.connect(db_path, timeout=30.0)
                cursor = conn.cursor()
                
                cursor.execute("SELECT Ingredient_Name, Variance, Notes FROM Inventory_Audit_Log WHERE Audit_ID = ?", (intake_id,))
                intake_row = cursor.fetchone()
                
                if not intake_row:
                    conn.close()
                    err_msg = urllib.parse.quote_plus(f"Database Error: Intake record {intake_id} not found.")
                    return redirect(f"/portal/{username}/corrections?error={err_msg}")
                
                item_name, variance, existing_notes = intake_row
                if "[VOIDED]" in str(existing_notes):
                    conn.close()
                    err_msg = urllib.parse.quote_plus("Duplicate Action: This intake entry has already been voided.")
                    return redirect(f"/portal/{username}/corrections?error={err_msg}")
                
                deduct_qty = abs(float(variance or 0.0))
                
                cursor.execute("""
                    UPDATE Ingredients 
                    SET Current_Stock = Current_Stock - ? 
                    WHERE Ingredient_Name = ? COLLATE NOCASE OR Ingredient_ID = ?
                """, (deduct_qty, item_name, item_name))
                
                new_notes = f"[VOIDED] {existing_notes or ''} | Auth: {operator} | Reason: {void_reason}"
                cursor.execute("""
                    UPDATE Inventory_Audit_Log 
                    SET Variance = 0.0, Notes = ? 
                    WHERE Audit_ID = ?
                """, (new_notes, intake_id))
                
                conn.commit()
                conn.close()
                
                feedback_msg = f"Success: Intake entry {intake_id} voided. Deducted {deduct_qty:g} units from inventory."
                alert_type = "success"
                
            except Exception as e:
                feedback_msg = f"Error processing intake void: {str(e)}"
                alert_type = "danger"

        # ---------------------------------------------------------
        # 4. PETTY CASH / EXPENSE VOID PROCESSING
        # ---------------------------------------------------------
        elif action == 'void_expense':
            expense_rowid = request.form.get('expense_rowid', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            
            if not expense_rowid or not void_reason:
                err_msg = urllib.parse.quote_plus("Compliance Violation: Expense ID and Void Reason are strictly required.")
                return redirect(f"/portal/{username}/corrections?error={err_msg}")
            
            try:
                conn = sqlite3.connect(db_path, timeout=30.0)
                cursor = conn.cursor()
                
                cursor.execute("SELECT Amount, Description FROM Expenses WHERE rowid = ?", (expense_rowid,))
                expense_record = cursor.fetchone()
                
                if not expense_record:
                    conn.close()
                    err_msg = urllib.parse.quote_plus("Database Error: Expense record not found.")
                    return redirect(f"/portal/{username}/corrections?error={err_msg}")
                
                original_desc = str(expense_record[1] or '')
                if "[VOIDED]" in original_desc:
                    conn.close()
                    err_msg = urllib.parse.quote_plus("Duplicate Action: This expense has already been voided.")
                    return redirect(f"/portal/{username}/corrections?error={err_msg}")
                
                new_desc = f"[VOIDED] {original_desc} | Auth: {operator} | Reason: {void_reason}"
                cursor.execute("UPDATE Expenses SET Amount = 0.0, Description = ? WHERE rowid = ?", (new_desc, expense_rowid))
                conn.commit()
                conn.close()
                
                feedback_msg = "Success: Expense neutralized to 0.00 in the general ledger."
                alert_type = "success"
                
            except Exception as e:
                feedback_msg = f"Error processing expense void: {str(e)}"
                alert_type = "danger"

        params = urllib.parse.urlencode({'msg': feedback_msg, 'alert_type': alert_type})
        return redirect(f"/portal/{username}/corrections?{params}")

    # =========================================================
    # UI DATA RETRIEVAL (OPTIMIZED SQL READS)
    # =========================================================
    recent_sales = []
    recent_waste = []
    recent_intake = []
    recent_expenses = []

    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Sales'")
        if cursor.fetchone():
            sales_cols = _get_table_columns(cursor, "Sales")
            order_clause = "Sale_Date DESC, Sale_Time DESC" if ('Sale_Date' in sales_cols and 'Sale_Time' in sales_cols) else "Sale_ID DESC"
            
            cursor.execute(f"""
                SELECT * FROM Sales 
                WHERE Sale_ID NOT LIKE 'VOID-%'
                ORDER BY {order_clause}
                LIMIT 100
            """)
            raw_sales = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT Sale_ID FROM Sales WHERE Sale_ID LIKE 'VOID-%'")
            voided_sale_ids = set(r[0].replace('VOID-', '') for r in cursor.fetchall())

            for sale in raw_sales:
                sale['is_voided'] = str(sale.get('Sale_ID', '')) in voided_sale_ids
                recent_sales.append(sale)

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Inventory_Audit_Log'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT * FROM Inventory_Audit_Log 
                ORDER BY Date DESC 
                LIMIT 250
            """)
            audit_logs = [dict(r) for r in cursor.fetchall()]

            for entry in audit_logs:
                audit_id = str(entry.get('Audit_ID', ''))
                notes = str(entry.get('Notes', ''))
                entry['is_voided'] = '[VOIDED]' in notes

                if audit_id.startswith('WST') or any(w in notes.lower() for w in ['waste', 'spoil', 'damaged', 'expired']):
                    if len(recent_waste) < 100:
                        recent_waste.append(entry)
                elif audit_id.startswith('RCV') or audit_id.startswith('AUD') or any(w in notes.lower() for w in ['intake', 'delivery', 'restock']):
                    if len(recent_intake) < 100:
                        recent_intake.append(entry)

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Expenses'")
        if cursor.fetchone():
            cursor.execute("SELECT rowid, * FROM Expenses ORDER BY rowid DESC LIMIT 100")
            for row in cursor.fetchall():
                exp = dict(row)
                desc = str(exp.get('Description', exp.get('Notes', '')))
                exp['is_voided'] = '[VOIDED]' in desc
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