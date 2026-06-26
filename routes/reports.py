# routes/reports.py
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB
import pandas as pd

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/portal/<username>/reports', methods=['GET'])
def web_reports_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect('/login')

    db = InventoryDB(f"data/client_{username}.db")

    # Aggregate Sales Data (Forced to Numeric to prevent string subtraction errors)
    sales_df = db.read_tab('Sales')
    total_revenue = 0.0
    recent_sales = []
    
    if not sales_df.empty and 'Total_Amount' in sales_df.columns:
        # Convert column to numeric, turning any weird text into 0, then sum it
        total_revenue = float(pd.to_numeric(sales_df['Total_Amount'], errors='coerce').fillna(0).sum())
        
        # Sort for the recent sales table
        if 'Sale_Date' in sales_df.columns:
            sales_df = sales_df.sort_values('Sale_Date', ascending=False)
        recent_sales = sales_df.head(15).to_dict('records')

    # Aggregate Expenses Data (Forced to Numeric)
    expenses_df = db.read_tab('Expenses')
    total_expenses = 0.0
    
    if not expenses_df.empty and 'Amount' in expenses_df.columns:
        # Convert column to numeric
        total_expenses = float(pd.to_numeric(expenses_df['Amount'], errors='coerce').fillna(0).sum())

    # Calculate Profit safely
    net_profit = total_revenue - total_expenses

    return render_template(
        'reports.html', 
        username=username,
        total_revenue=total_revenue,
        total_expenses=total_expenses,
        net_profit=net_profit,
        recent_sales=recent_sales
    )