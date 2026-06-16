# routes/reports.py - Reports Module Blueprint
from flask import Blueprint, redirect, session, render_template
from modules.database import InventoryDB

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/portal/<username>/reports')
def web_reports_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    sales_df = client_db.read_tab('Sales')
    expenses_df = client_db.read_tab('Expenses')
    products_df = client_db.get_all_products()
    
    # Run bookkeeping calculations
    total_sales = sales_df['Total_Amount'].sum() if (not sales_df.empty and 'Total_Amount' in sales_df.columns) else 0.0
    total_exp = expenses_df['Amount'].sum() if (not expenses_df.empty and 'Amount' in expenses_df.columns) else 0.0
    
    # 1. Product ranking dataframe aggregation maps
    product_summary_list = []
    if not sales_df.empty and 'Product_ID' in sales_df.columns:
        summary = sales_df.groupby('Product_ID').agg({'Quantity': 'sum', 'Total_Amount': 'sum'}).reset_index().sort_values('Total_Amount', ascending=False)
        for _, r in summary.iterrows():
            p_name = products_df[products_df['Product_ID'] == r['Product_ID']]['Product_Name'].values[0] if not products_df.empty and not products_df[products_df['Product_ID'] == r['Product_ID']].empty else r['Product_ID']
            product_summary_list.append({'Product_Name': p_name, 'Quantity': r['Quantity'], 'Total_Amount': r['Total_Amount']})
            
    # 2. Cost structure grouping metrics arrays
    expense_summary_list = expenses_df.groupby('Category')['Amount'].sum().reset_index().sort_values('Amount', ascending=False).to_dict(orient='records') if not expenses_df.empty and 'Category' in expenses_df.columns else []

    return render_template(
        'reports.html', 
        username=username, 
        total_sales=total_sales, 
        total_expenses=total_exp, 
        net_profit=(total_sales - total_exp), 
        product_summary=product_summary_list, 
        expense_summary=expense_summary_list
    )