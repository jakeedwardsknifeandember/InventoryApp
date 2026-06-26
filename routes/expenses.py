# routes/expenses.py - COMPLETE AND NUMERIC SAFE
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
from datetime import datetime
import pandas as pd  # Added to enforce number formatting

expenses_bp = Blueprint('expenses', __name__)

@expenses_bp.route('/portal/<username>/expenses', methods=['GET', 'POST'])
def web_expenses_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect('/login')

    db = InventoryDB(f"data/client_{username}.db")

    if request.method == 'POST':
        action = request.form.get('action_type')
        
        if action == 'add_expense':
            db.add_expense({
                'Expense_Date': request.form.get('expense_date', datetime.now().strftime("%Y-%m-%d")),
                'Expense_Type': request.form.get('expense_type', 'General'),
                'Description': request.form.get('description', ''),
                'Amount': float(request.form.get('amount', 0.0)),
                'Category': request.form.get('category', 'Misc'),
                'Payment_Method': request.form.get('payment_method', 'Cash'),
                'Notes': request.form.get('notes', '')
            })
        elif action == 'delete_expense':
            db.delete_expense(request.form.get('expense_id'))
            
        return redirect(f"/portal/{username}/expenses")

    # Fetch data for view
    expenses_df = db.get_expenses()
    
    # 🌟 SAFTEY FIX: Force the 'Amount' column to be a real number before formatting
    if not expenses_df.empty and 'Amount' in expenses_df.columns:
        expenses_df['Amount'] = pd.to_numeric(expenses_df['Amount'], errors='coerce').fillna(0.0)
        
    expenses_list = expenses_df.to_dict('records') if not expenses_df.empty else []

    return render_template('expenses.html', username=username, expenses=expenses_list)