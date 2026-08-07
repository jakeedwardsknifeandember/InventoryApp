# routes/corrections.py - Secure Voids and Corrections Module
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd
import sqlite3
from datetime import datetime

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
        
        # SALES VOID PROCESSING
        if action == 'void_sale':
            sale_id = request.form.get('sale_id', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            operator = session.get('logged_in_user', 'System')
            
            if not sale_id or not void_reason:
                return redirect(f"/portal/{username}/corrections?error=Compliance Violation: Sale ID and Void Reason are strictly required.")
                
            try:
                conn = sqlite3.connect(db_path, timeout=20.0)
                cursor = conn.cursor()
                
                cursor.execute("SELECT Product_ID, Quantity, Total_Amount, Sale_Date FROM Sales WHERE Sale_ID = ?", (sale_id,))
                sale_record = cursor.fetchone()
                
                if not sale_record:
                    conn.close()
                    return redirect(f"/portal/{username}/corrections?error=Database Error: Sale ID {sale_id} not found.")
                    
                p_id, original_qty, original_amt, original_sale_date = sale_record
                
                system_time_exact = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                void_sale_id = f"VOID-{sale_id}"
                
                cursor.execute("SELECT COUNT(*) FROM Sales WHERE Sale_ID = ?", (void_sale_id,))
                if cursor.fetchone()[0] > 0:
                    conn.close()
                    return redirect(f"/portal/{username}/corrections?error=Duplicate Action: This transaction has already been voided.")

                cursor.execute("""
                    INSERT INTO Sales (Sale_ID, Product_ID, Quantity, Sale_Date, Sale_Time, Total_Amount, Unit_Cost, Entry_Reason, System_Timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (void_sale_id, p_id, -original_qty, original_sale_date, datetime.now().strftime("%H:%M:%S"), -original_amt, 0.0, f"VOID: {void_reason}", system_time_exact))
                
                conn.commit()
                conn.close()

                client_db.update_inventory_from_sale(p_id, -original_qty)

                audit_df = client_db.read_tab('Inventory_Audit_Log')
                if audit_df is None or audit_df.empty:
                    audit_df = pd.DataFrame(columns=['Audit_ID', 'Date', 'Ingredient_Name', 'Theoretical', 'Physical', 'Variance', 'Notes', 'Updated_By'])
                
                if 'Updated_By' not in audit_df.columns:
                    audit_df['Updated_By'] = 'System'

                new_audit = {
                    'Audit_ID': void_sale_id,
                    'Date': system_time_exact,
                    'Ingredient_Name': f"Product Refund: {p_id}",
                    'Theoretical': 0.0, 
                    'Physical': 0.0,
                    'Variance': original_qty, 
                    'Notes': f"MANAGER VOID AUTHORIZED. Reason: {void_reason}",
                    'Updated_By': operator
                }
                
                audit_df = pd.concat([audit_df, pd.DataFrame([new_audit])], ignore_index=True)
                client_db.save_tab('Inventory_Audit_Log', audit_df)

                feedback_msg = f"Success: Sale {sale_id} voided. Revenue deducted from original date, inventory restocked, and audit log stamped."
                alert_type = "success"

            except Exception as e:
                feedback_msg = f"Error processing void: {str(e)}"
                alert_type = "danger"

        # WASTAGE VOID PROCESSING (Neutralization Method)
        elif action == 'void_waste':
            waste_id = request.form.get('waste_id', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            operator = session.get('logged_in_user', 'System')
            
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
                
                # Prevent duplicate voiding of the same log
                if "[VOIDED]" in str(audit_df.at[idx, 'Notes']):
                    return redirect(f"/portal/{username}/corrections?error=Duplicate Action: This wastage entry has already been voided.")
                    
                item_target = str(audit_df.at[idx, 'Ingredient_Name'])
                original_variance = float(audit_df.at[idx, 'Variance'])
                
                refund_qty = abs(original_variance)
                
                # Restock the physical inventory mathematically
                conn = sqlite3.connect(db_path, timeout=20.0)
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(Ingredients)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'Current_Stock' in cols:
                    cursor.execute("UPDATE Ingredients SET Current_Stock = Current_Stock + ? WHERE Ingredient_Name = ? OR Ingredient_ID = ?", (refund_qty, item_target, item_target))
                conn.commit()
                conn.close()
                
                # Neutralize original entry to force the financial dashboard to drop the expense calculation
                original_notes = str(audit_df.at[idx, 'Notes'])
                audit_df.at[idx, 'Variance'] = 0.0
                audit_df.at[idx, 'Notes'] = f"[VOIDED] {original_notes} | Auth: {operator} | Reason: {void_reason}"
                
                client_db.save_tab('Inventory_Audit_Log', audit_df)
                
                feedback_msg = f"Success: Waste entry {waste_id} neutralized. Inventory restored and financial reports updated."
                alert_type = "success"
                
            except Exception as e:
                feedback_msg = f"Error processing waste void: {str(e)}"
                alert_type = "danger"

        return redirect(f"/portal/{username}/corrections?msg={feedback_msg}&alert_type={alert_type}")

    # FETCH SALES FOR UI
    sales_df = client_db.read_tab('Sales')
    recent_sales = []
    
    if not sales_df.empty:
        void_records = sales_df[sales_df['Sale_ID'].astype(str).str.startswith('VOID-', na=False)]
        voided_ids = set([str(vid).replace('VOID-', '') for vid in void_records['Sale_ID'].tolist()])
        
        valid_sales = sales_df[~sales_df['Sale_ID'].astype(str).str.startswith('VOID', na=False)]
        
        if 'System_Timestamp' in valid_sales.columns:
            valid_sales = valid_sales.sort_values('System_Timestamp', ascending=False)
        else:
            valid_sales = valid_sales.sort_values('Sale_ID', ascending=False)
            
        recent_sales_raw = valid_sales.head(100).to_dict(orient='records')
        
        for sale in recent_sales_raw:
            sale['is_voided'] = sale['Sale_ID'] in voided_ids
            recent_sales.append(sale)
            
    # FETCH WASTAGE FOR UI
    audit_df = client_db.read_tab('Inventory_Audit_Log')
    recent_waste = []
    
    if audit_df is not None and not audit_df.empty:
        waste_mask = audit_df['Audit_ID'].astype(str).str.startswith('WST', na=False) | audit_df['Notes'].astype(str).str.contains('Waste|Spoil', case=False, na=False)
        valid_waste = audit_df[waste_mask]
        
        if 'Date' in valid_waste.columns:
            valid_waste = valid_waste.sort_values('Date', ascending=False)
            
        recent_waste_raw = valid_waste.head(100).to_dict(orient='records')
        
        for waste in recent_waste_raw:
            waste['is_voided'] = '[VOIDED]' in str(waste.get('Notes', ''))
            recent_waste.append(waste)

    server_error = request.args.get('error', '')
    if server_error:
        feedback_msg = server_error
        alert_type = "danger"

    return render_template(
        'corrections.html',
        username=username,
        recent_sales=recent_sales,
        recent_waste=recent_waste,
        msg=request.args.get('msg', feedback_msg),
        alert_type=request.args.get('alert_type', alert_type)
    )