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
    
    # 🔒 STRICT ROLE BLOCK: Only authorized management can access this route
    if staff_role not in ['Platform Owner Admin', 'Store Manager']:
        return redirect(f"/portal/{username}/sales?error=Security Block: Only Managers and Admins can access the Corrections module.")

    db_path = f"data/client_{username}.db"
    client_db = InventoryDB(db_path)
    feedback_msg = None
    alert_type = "success"

    if request.method == 'POST':
        action = request.form.get('action_type')
        
        if action == 'void_sale':
            sale_id = request.form.get('sale_id', '').strip()
            void_reason = request.form.get('void_reason', '').strip()
            operator = session.get('logged_in_user', 'System')
            
            if not sale_id or not void_reason:
                return redirect(f"/portal/{username}/corrections?error=Compliance Violation: Sale ID and Void Reason are strictly required.")
                
            try:
                conn = sqlite3.connect(db_path, timeout=20.0)
                cursor = conn.cursor()
                
                # Fetch original sale data ALONG WITH the original Sale_Date
                cursor.execute("SELECT Product_ID, Quantity, Total_Amount, Sale_Date FROM Sales WHERE Sale_ID = ?", (sale_id,))
                sale_record = cursor.fetchone()
                
                if not sale_record:
                    conn.close()
                    return redirect(f"/portal/{username}/corrections?error=Database Error: Sale ID {sale_id} not found.")
                    
                p_id, original_qty, original_amt, original_sale_date = sale_record
                
                system_time_exact = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                void_sale_id = f"VOID-{sale_id}"
                
                # Prevent duplicate voids
                cursor.execute("SELECT COUNT(*) FROM Sales WHERE Sale_ID = ?", (void_sale_id,))
                if cursor.fetchone()[0] > 0:
                    conn.close()
                    return redirect(f"/portal/{username}/corrections?error=Duplicate Action: This transaction has already been voided.")

                # 1. Add negative financial offset to Sales table using the ORIGINAL date
                cursor.execute("""
                    INSERT INTO Sales (Sale_ID, Product_ID, Quantity, Sale_Date, Sale_Time, Total_Amount, Unit_Cost, Entry_Reason, System_Timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (void_sale_id, p_id, -original_qty, original_sale_date, datetime.now().strftime("%H:%M:%S"), -original_amt, 0.0, f"VOID: {void_reason}", system_time_exact))
                
                conn.commit()
                conn.close()

                # 2. Refund Inventory (Reverse the deduction)
                client_db.update_inventory_from_sale(p_id, -original_qty)

                # 3. Force Strict Audit Log Entry for permanent tracking
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

        return redirect(f"/portal/{username}/corrections?msg={feedback_msg}&alert_type={alert_type}")

    # GET METHOD: Fetch Recent Sales for the Void Interface
    sales_df = client_db.read_tab('Sales')
    recent_sales = []
    
    if not sales_df.empty:
        # Find all void records to map against original sales
        void_records = sales_df[sales_df['Sale_ID'].astype(str).str.startswith('VOID-', na=False)]
        voided_ids = set([str(vid).replace('VOID-', '') for vid in void_records['Sale_ID'].tolist()])
        
        # Isolate standard sales
        valid_sales = sales_df[~sales_df['Sale_ID'].astype(str).str.startswith('VOID', na=False)]
        
        if 'System_Timestamp' in valid_sales.columns:
            valid_sales = valid_sales.sort_values('System_Timestamp', ascending=False)
        else:
            valid_sales = valid_sales.sort_values('Sale_ID', ascending=False)
            
        recent_sales_raw = valid_sales.head(100).to_dict(orient='records')
        
        # Tag each sale with its void status
        for sale in recent_sales_raw:
            sale['is_voided'] = sale['Sale_ID'] in voided_ids
            recent_sales.append(sale)

    server_error = request.args.get('error', '')
    if server_error:
        feedback_msg = server_error
        alert_type = "danger"

    return render_template(
        'corrections.html',
        username=username,
        recent_sales=recent_sales,
        msg=request.args.get('msg', feedback_msg),
        alert_type=request.args.get('alert_type', alert_type)
    )