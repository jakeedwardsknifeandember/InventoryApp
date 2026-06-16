# routes/expenses.py - Expenses Module Blueprint
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
from datetime import datetime
import sqlite3

expenses_bp = Blueprint('expenses', __name__)

@expenses_bp.route('/portal/<username>/expenses', methods=['GET', 'POST'])
def web_expenses_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    feedback_msg = None
    if request.method == 'POST':
        category, description = request.form.get('category'), request.form.get('description', '')
        try:
            amount = float(request.form.get('amount', 0))
            conn = sqlite3.connect(client_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM Expenses")
            expense_id = f"EXP{cursor.fetchone()[0] + 1:04d}"
            cursor.execute("INSERT INTO Expenses (Expense_ID, Category, Amount, Expense_Date, Description) VALUES (?, ?, ?, ?, ?)", (expense_id, category, amount, datetime.now().strftime("%Y-%m-%d"), description))
            conn.commit()
            conn.close()
            feedback_msg = f"✅ Expense recorded successfully: {expense_id} (-₱{amount:.2f})"
        except ValueError: 
            feedback_msg = "❌ Error: Invalid input parameters."
            
    expenses_df = client_db.read_tab('Expenses')
    expenses_list = expenses_df.to_dict(orient='records') if not expenses_df.empty else []
    
    return render_template(
        'expenses.html', 
        username=username, 
        expenses_history=expenses_list, 
        msg=feedback_msg
    )