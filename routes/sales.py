# routes/sales.py - Sales Module Blueprint
from flask import Blueprint, request, redirect, session, render_template
from modules.database import InventoryDB

sales_bp = Blueprint('sales', __name__)

@sales_bp.route('/portal/<username>/sales', methods=['GET', 'POST'])
def web_sales_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    feedback_msg = None
    
    # Process sale checkout transactions
    if request.method == 'POST':
        prod_id = request.form.get('product_id')
        try:
            qty_sold = float(request.form.get('quantity', 0))
            products_df = client_db.get_all_products()
            prod_row = products_df[products_df['Product_ID'] == prod_id]
            if not prod_row.empty:
                unit_price = float(prod_row['Selling_Price'].values[0])
                stock_ok, stock_msg = client_db.update_inventory_from_sale(prod_id, qty_sold)
                if stock_ok:
                    if client_db.add_sale(prod_id, qty_sold, unit_price): 
                        feedback_msg = f"💰 Checkout Success! Total: ₱{qty_sold * unit_price:.2f}."
                else: 
                    feedback_msg = f"⚠️ Blocked! {stock_msg}"
        except ValueError: 
            feedback_msg = "❌ Error: Invalid quantity fields."

    sales_df = client_db.read_tab('Sales')
    products_df = client_db.get_all_products()
    
    # Prepare historical logging maps with human-readable names
    sales_list = []
    if not sales_df.empty:
        for _, r in sales_df.sort_values('Sale_ID', ascending=False).iterrows():
            p_name = r['Product_ID']
            if not products_df.empty:
                match = products_df[products_df['Product_ID'] == r['Product_ID']]
                if not match.empty: 
                    p_name = match['Product_Name'].values[0]
            sales_list.append({
                'Sale_ID': r['Sale_ID'], 'Product_Name': p_name,
                'Quantity': r['Quantity'], 'Sale_Date': r['Sale_Date'],
                'Sale_Time': r['Sale_Time'] if 'Sale_Time' in sales_df.columns else '',
                'Total_Amount': r['Total_Amount']
            })

    dropdown_p = products_df.to_dict(orient='records') if not products_df.empty else []

    return render_template(
        'sales.html',
        username=username,
        dropdown_products=dropdown_p,
        sales_history=sales_list,
        msg=feedback_msg
    )