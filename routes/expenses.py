# routes/expenses.py - Advanced Business Analytics & Filtering Engine
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
from datetime import datetime
import pandas as pd

expenses_bp = Blueprint('expenses', __name__)

@expenses_bp.route('/portal/<username>/expenses', methods=['GET', 'POST'])
def web_expenses_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')

    db = InventoryDB(f"data/client_{username}.db")
    feedback_msg = None
    alert_type = "success"

    # ==========================================
    # 📥 1. POST METHOD: DATA WRITE OPERATIONS
    # ==========================================
    if request.method == 'POST':
        action = request.form.get('action_type')
        
        if action == 'add_expense':
            expense_date = request.form.get('expense_date', datetime.now().strftime("%Y-%m-%d")).strip()
            description = request.form.get('description', '').strip()
            amount_str = request.form.get('amount', '0.0')
            category = request.form.get('category', 'Misc').strip()
            payment_method = request.form.get('payment_method', 'Cash').strip()
            
            try:
                amount = float(amount_str)
                if amount <= 0:
                    feedback_msg = "❌ Error: Expense amount must be greater than ₱0.00."
                    alert_type = "danger"
                elif not description:
                    feedback_msg = "❌ Error: Description field cannot be blank."
                    alert_type = "danger"
                else:
                    success, msg = db.add_expense({
                        'Expense_Date': expense_date,
                        'Expense_Type': 'Operational', 
                        'Description': description,
                        'Amount': amount,
                        'Category': category if category else 'Misc',
                        'Payment_Method': payment_method if payment_method else 'Cash',
                        'Notes': request.form.get('notes', '').strip()
                    })
                    feedback_msg = msg
                    alert_type = "success" if success else "danger"
            except ValueError:
                feedback_msg = "❌ Error: Invalid numeric formatting supplied in Amount field."
                alert_type = "danger"
                
        elif action == 'delete_expense':
            expense_id = request.form.get('expense_id')
            success, msg = db.delete_expense(expense_id)
            feedback_msg = msg
            alert_type = "success" if success else "danger"
            
        return redirect(f"/portal/{username}/expenses?msg={feedback_msg}&alert_type={alert_type}")

    # ==========================================
    # 📤 2. GET METHOD: DATA RECOVERY & ANALYTICS
    # ==========================================
    url_msg = request.args.get('msg')
    url_alert = request.args.get('alert_type', 'success')
    if url_msg:
        feedback_msg = url_msg
        alert_type = url_alert

    expenses_df = db.get_expenses()
    
    total_this_month = 0.0
    top_burning_category = "None logged"
    cash_ratio = 50.0  
    gcash_ratio = 50.0
    
    # 💥 SECURITY CRITICAL CHANGE: "Raw Ingredients" stripped to prevent double-entry vulnerability
    categories_list = ["Utilities", "Rent & Lease", "Staff Salaries", "Packaging", "Equipment Maintenance", "Misc"]
    
    search_query = request.args.get('search', '').lower().strip()
    selected_category = request.args.get('category', 'All')
    selected_period = request.args.get('period', 'this_month') 

    if not expenses_df.empty:
        expenses_df['Amount'] = pd.to_numeric(expenses_df['Amount'], errors='coerce').fillna(0.0)
        expenses_df['Expense_Date'] = pd.to_datetime(expenses_df['Expense_Date'], errors='coerce')
        
        if 'Category' in expenses_df.columns:
            db_categories = expenses_df['Category'].dropna().unique().tolist()
            categories_list = sorted(list(set(categories_list + [str(c) for c in db_categories if c and str(c).strip()])))

        now = datetime.now()
        current_year = now.year
        current_month = now.month
        
        this_month_mask = (expenses_df['Expense_Date'].dt.year == current_year) & (expenses_df['Expense_Date'].dt.month == current_month)
        this_month_df = expenses_df[this_month_mask]
        total_this_month = float(this_month_df['Amount'].sum())
        
        analytics_df = this_month_df if not this_month_df.empty else expenses_df
        if not analytics_df.empty:
            cat_group = analytics_df.groupby('Category')['Amount'].sum()
            if not cat_group.empty:
                top_cat_name = cat_group.idxmax()
                top_cat_sum = cat_group.max()
                top_burning_category = f"{top_cat_name} (₱{top_cat_sum:,.2f})"

        total_all_time = expenses_df['Amount'].sum()
        if total_all_time > 0:
            cash_mask = expenses_df['Payment_Method'].astype(str).str.lower().str.strip().isin(['cash', 'petty cash'])
            total_cash = expenses_df[cash_mask]['Amount'].sum()
            cash_ratio = round((total_cash / total_all_time) * 100, 1)
            gcash_ratio = round(100.0 - cash_ratio, 1)

        # ==========================================
        # 🔍 3. FRONTEND SEARCH & FILTER PROCESSING
        # ==========================================
        if selected_period == 'this_month':
            expenses_df = expenses_df[this_month_mask]
        elif selected_period == 'last_month':
            last_month = 12 if current_month == 1 else current_month - 1
            last_year = current_year - 1 if current_month == 1 else current_year
            last_month_mask = (expenses_df['Expense_Date'].dt.year == last_year) & (expenses_df['Expense_Date'].dt.month == last_month)
            expenses_df = expenses_df[last_month_mask]
            
        if selected_category != 'All':
            expenses_df = expenses_df[expenses_df['Category'].astype(str) == selected_category]
            
        if search_query:
            expenses_df = expenses_df[
                expenses_df['Description'].astype(str).str.lower().str.contains(search_query) |
                expenses_df['Category'].astype(str).str.lower().str.contains(search_query)
            ]

        final_list = []
        for _, row in expenses_df.iterrows():
            date_str = datetime.now().strftime("%Y-%m-%d")
            if pd.notnull(row['Expense_Date']):
                date_str = row['Expense_Date'].strftime("%Y-%m-%d")
                
            p_method = str(row.get('Payment_Method') or 'Cash').strip()
            category_val = str(row.get('Category') or 'Misc').strip()
            
            if p_method == 'nan' or not p_method: p_method = 'Cash'
            if category_val == 'nan' or not category_val: category_val = 'Misc'
            
            final_list.append({
                'Expense_ID': row.get('Expense_ID', ''),
                'Expense_Date': date_str,
                'Description': str(row.get('Description') or '').strip(),
                'Category': category_val,
                'Payment_Method': p_method,
                'Amount': float(row.get('Amount', 0.0)),
                'Notes': str(row.get('Notes') or '').strip()
            })
    else:
        final_list = []

    return render_template(
        'expenses.html',
        username=username,
        expenses=final_list,
        categories=categories_list,
        kpi_month_total=total_this_month,
        kpi_top_burn=top_burning_category,
        kpi_cash_ratio=cash_ratio,
        kpi_digital_ratio=gcash_ratio,
        msg=feedback_msg,
        alert_type=alert_type,
        current_search=search_query,
        current_category=selected_category,
        current_period=selected_period
    )