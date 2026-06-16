# app.py - Production SaaS Engine (Fully Modular Template Architecture)
from flask import Flask, request, redirect, url_for, session, render_template
from modules.database import InventoryDB
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'knife-and-ember-secret-saas-key'

USER_DB_PATH = "data/users.db"

def initialize_user_database():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(USER_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password TEXT NOT NULL, database_file TEXT NOT NULL, subscription_status TEXT NOT NULL
        )
    ''')
    cursor.execute("INSERT OR REPLACE INTO users VALUES ('bakery', 'bakery123', 'data/client_bakery.db', 'Active')")
    conn.commit()
    conn.close()

initialize_user_database()

def ensure_starter_data(client_db_path, client_db):
    try:
        ing_df = client_db.get_inventory_status()
        if ing_df.empty:
            client_db.add_ingredient({
                'Ingredient_ID': 'ING001', 'Ingredient_Name': 'Premium Flour', 
                'Unit': 'kg', 'Current_Stock': 50.0, 'Min_Stock_Level': 10.0,
                'Category': 'Baking', 'Cost_Per_Unit': 45.0, 'Supplier': 'Main Dist',
                'Description': 'Starter Flour', 'Active': 'Yes'
            })
        
        prod_df = client_db.get_all_products()
        if prod_df.empty:
            client_db.add_product({
                'Product_ID': 'PROD001', 'Product_Name': 'Signature Fudge Brownie', 
                'Category': 'Pastries', 'Selling_Price': 45.0, 'Active': 'Yes', 'Notes': 'Best seller'
            })
            
        conn = sqlite3.connect(client_db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Recipes WHERE ROWID NOT IN (SELECT MIN(ROWID) FROM Recipes GROUP BY Product_ID, Ingredient_ID)")
        cursor.execute("SELECT 1 FROM Recipes WHERE Product_ID = 'PROD001' AND Ingredient_ID = 'ING001'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO Recipes (Product_ID, Ingredient_ID, Quantity_Required) VALUES ('PROD001', 'ING001', 0.25)")
            
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Expenses (
                Expense_ID TEXT PRIMARY KEY, Category TEXT, Amount REAL, Expense_Date TEXT, Description TEXT
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database seed note: {e}")

@app.route('/')
def index():
    if 'logged_in_user' in session: return redirect(url_for('client_portal', username=session['logged_in_user']))
    return redirect(url_for('login'))

# 🔒 LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        input_user = request.form['username'].lower().strip()
        input_pass = request.form['password']
        conn = sqlite3.connect(USER_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT password, subscription_status FROM users WHERE username = ?", (input_user,))
        user_record = cursor.fetchone()
        conn.close()
        if user_record and input_pass == user_record[0] and user_record[1] == 'Active':
            session['logged_in_user'] = input_user
            return redirect(url_for('client_portal', username=input_user))
        error = "❌ Invalid credentials."
    return render_template('login.html', error=error)

# 📊 DASHBOARD
@app.route('/portal/<username>')
def client_portal(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect(url_for('login'))
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    ensure_starter_data(client_db_path, client_db)
    
    products_df = client_db.get_all_products()
    total_products = len(products_df) if not products_df.empty else 0
    inventory_df = client_db.get_inventory_status()
    low_stock_count = len(inventory_df[inventory_df['Status'] == 'Low Stock']) if not inventory_df.empty else 0
    sales_df = client_db.read_tab('Sales')
    total_revenue = sales_df['Total_Amount'].sum() if (not sales_df.empty and 'Total_Amount' in sales_df.columns) else 0.0
    expenses_df = client_db.read_tab('Expenses')
    total_expenses = expenses_df['Amount'].sum() if (not expenses_df.empty and 'Amount' in expenses_df.columns) else 0.0

    return render_template(
        'dashboard.html', username=username, total_products=total_products,
        total_revenue=total_revenue, low_stock_count=low_stock_count, total_expenses=total_expenses
    )

# 🍎 INGREDIENTS
@app.route('/portal/<username>/ingredients', methods=['GET', 'POST'])
def web_ingredients_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect(url_for('login'))
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    ensure_starter_data(client_db_path, client_db)
    
    feedback_msg, current_tab = None, request.args.get('tab', 'view')
    if request.method == 'POST' and request.form.get('action_type') == 'add_new_item':
        new_id = client_db.generate_ingredient_id()
        success, message = client_db.add_ingredient({
            'Ingredient_ID': new_id, 'Ingredient_Name': request.form.get('name'), 'Unit': request.form.get('unit'),
            'Category': request.form.get('category'), 'Current_Stock': request.form.get('stock'),
            'Min_Stock_Level': request.form.get('min_stock'), 'Cost_Per_Unit': request.form.get('cost'),
            'Supplier': request.form.get('supplier'), 'Description': request.form.get('description'), 'Active': 'Yes'
        })
        feedback_msg = f"✅ Success: Added {request.form.get('name')}!" if success else f"❌ Error: {message}"
        if success: current_tab = 'view'

    inventory_df = client_db.get_inventory_status()
    search_query = request.args.get('search', '').lower().strip()
    filter_status = request.args.get('filter_status', 'all')
    if not inventory_df.empty:
        if search_query: inventory_df = inventory_df[inventory_df['Ingredient_Name'].str.lower().str.contains(search_query)]
        if filter_status == 'low': inventory_df = inventory_df[inventory_df['Status'] == 'Low Stock']
        elif filter_status == 'critical': inventory_df = inventory_df[inventory_df['Status'] == 'Critical']
    ingredients_list = inventory_df.to_dict(orient='records') if not inventory_df.empty else []
    return render_template('ingredients.html', username=username, current_tab=current_tab, ingredients=ingredients_list, search_query=search_query, filter_status=filter_status, msg=feedback_msg)

# 📦 PRODUCTS
@app.route('/portal/<username>/products', methods=['GET', 'POST'])
def web_products_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect(url_for('login'))
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    ensure_starter_data(client_db_path, client_db)
    
    feedback_msg, current_tab = None, request.args.get('tab', 'view')
    if request.method == 'POST' and request.form.get('action_type') == 'add_product':
        new_id = client_db.generate_product_id()
        success, message = client_db.add_product({
            'Product_ID': new_id, 'Product_Name': request.form.get('name'), 'Category': request.form.get('category'),
            'Selling_Price': float(request.form.get('selling_price', 0)), 'Active': 'Yes', 'Notes': request.form.get('notes', '')
        })
        feedback_msg = f"✅ Success: Added Product '{request.form.get('name')}'!" if success else f"❌ Error: {message}"
        if success: current_tab = 'view'
        
    products_df = client_db.get_all_products()
    products_list = products_df.to_dict(orient='records') if not products_df.empty else []
    return render_template('products.html', username=username, current_tab=current_tab, products=products_list, msg=feedback_msg)

# 🍕 RECIPES
@app.route('/portal/<username>/recipes', methods=['GET', 'POST'])
def web_recipes_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect(url_for('login'))
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    ensure_starter_data(client_db_path, client_db)
    
    feedback_msg = None
    if request.method == 'POST':
        p_id, i_id = request.form.get('product_id'), request.form.get('ingredient_id')
        try:
            qty_req = float(request.form.get('quantity_required', 0))
            conn = sqlite3.connect(client_db_path); cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM Recipes WHERE Product_ID = ? AND Ingredient_ID = ?", (p_id, i_id))
            if cursor.fetchone(): cursor.execute("UPDATE Recipes SET Quantity_Required = ? WHERE Product_ID = ? AND Ingredient_ID = ?", (qty_req, p_id, i_id))
            else: cursor.execute("INSERT INTO Recipes (Product_ID, Ingredient_ID, Quantity_Required) VALUES (?, ?, ?)", (p_id, i_id, qty_req))
            conn.commit(); conn.close()
            feedback_msg = "🔄 Recipe link row updated successfully!"
        except ValueError: feedback_msg = "❌ Error: Please input a valid numeric quantity value."
        
    products_df = client_db.get_all_products(); ingredients_df = client_db.get_inventory_status()
    dropdown_p = products_df.to_dict(orient='records') if not products_df.empty else []
    dropdown_i = ingredients_df.to_dict(orient='records') if not ingredients_df.empty else []
    matrix_rows = []
    if not products_df.empty:
        for _, row in products_df.iterrows():
            recipe_df = client_db.get_product_recipes(row['Product_ID'])
            matrix_rows.append({'product_id': row['Product_ID'], 'product_name': row['Product_Name'], 'category': row['Category'], 'recipe_items': recipe_df.to_dict(orient='records') if not recipe_df.empty else []})
    return render_template('recipes.html', username=username, dropdown_products=dropdown_p, dropdown_ingredients=dropdown_i, matrix_rows=matrix_rows, msg=feedback_msg)

# 💰 SALES
@app.route('/portal/<username>/sales', methods=['GET', 'POST'])
def web_sales_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect(url_for('login'))
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    ensure_starter_data(client_db_path, client_db)
    
    feedback_msg = None
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
                    if client_db.add_sale(prod_id, qty_sold, unit_price): feedback_msg = f"💰 Checkout Success! Total: ₱{qty_sold * unit_price:.2f}."
                else: feedback_msg = f"⚠️ Blocked! {stock_msg}"
        except ValueError: feedback_msg = "❌ Error: Invalid quantity fields."
        
    sales_df = client_db.read_tab('Sales'); products_df = client_db.get_all_products()
    sales_list = []
    if not sales_df.empty:
        for _, r in sales_df.sort_values('Sale_ID', ascending=False).iterrows():
            p_name = products_df[products_df['Product_ID'] == r['Product_ID']]['Product_Name'].values[0] if not products_df.empty and not products_df[products_df['Product_ID'] == r['Product_ID']].empty else r['Product_ID']
            sales_list.append({'Sale_ID': r['Sale_ID'], 'Product_Name': p_name, 'Quantity': r['Quantity'], 'Sale_Date': r['Sale_Date'], 'Sale_Time': r['Sale_Time'] if 'Sale_Time' in sales_df.columns else '', 'Total_Amount': r['Total_Amount']})
    dropdown_p = products_df.to_dict(orient='records') if not products_df.empty else []
    return render_template('sales.html', username=username, dropdown_products=dropdown_p, sales_history=sales_list, msg=feedback_msg)

# 📦 INVENTORY
@app.route('/portal/<username>/inventory')
def web_inventory_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect(url_for('login'))
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    ensure_starter_data(client_db_path, client_db)
    inventory_df = client_db.get_inventory_status()
    inventory_list = inventory_df.to_dict(orient='records') if not inventory_df.empty else []
    return render_template('inventory.html', username=username, inventory_status=inventory_list)

# 💸 EXPENSES
@app.route('/portal/<username>/expenses', methods=['GET', 'POST'])
def web_expenses_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect(url_for('login'))
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    ensure_starter_data(client_db_path, client_db)
    
    feedback_msg = None
    if request.method == 'POST':
        category, description = request.form.get('category'), request.form.get('description', '')
        try:
            amount = float(request.form.get('amount', 0))
            conn = sqlite3.connect(client_db_path); cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM Expenses")
            expense_id = f"EXP{cursor.fetchone()[0] + 1:04d}"
            cursor.execute("INSERT INTO Expenses (Expense_ID, Category, Amount, Expense_Date, Description) VALUES (?, ?, ?, ?, ?)", (expense_id, category, amount, datetime.now().strftime("%Y-%m-%d"), description))
            conn.commit(); conn.close()
            feedback_msg = f"✅ Expense recorded successfully: {expense_id} (-₱{amount:.2f})"
        except ValueError: feedback_msg = "❌ Error: Invalid input parameters."
        
    expenses_df = client_db.read_tab('Expenses')
    expenses_list = expenses_df.to_dict(orient='records') if not expenses_df.empty else []
    return render_template('expenses.html', username=username, expenses_history=expenses_list, msg=feedback_msg)

# 📊 REPORTS
@app.route('/portal/<username>/reports')
def web_reports_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect(url_for('login'))
    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    ensure_starter_data(client_db_path, client_db)
    
    sales_df = client_db.read_tab('Sales'); expenses_df = client_db.read_tab('Expenses'); products_df = client_db.get_all_products()
    total_sales = sales_df['Total_Amount'].sum() if (not sales_df.empty and 'Total_Amount' in sales_df.columns) else 0.0
    total_exp = expenses_df['Amount'].sum() if (not expenses_df.empty and 'Amount' in expenses_df.columns) else 0.0
    
    product_summary_list = []
    if not sales_df.empty and 'Product_ID' in sales_df.columns:
        summary = sales_df.groupby('Product_ID').agg({'Quantity': 'sum', 'Total_Amount': 'sum'}).reset_index().sort_values('Total_Amount', ascending=False)
        for _, r in summary.iterrows():
            p_name = products_df[products_df['Product_ID'] == r['Product_ID']]['Product_Name'].values[0] if not products_df.empty and not products_df[products_df['Product_ID'] == r['Product_ID']].empty else r['Product_ID']
            product_summary_list.append({'Product_Name': p_name, 'Quantity': r['Quantity'], 'Total_Amount': r['Total_Amount']})
            
    expense_summary_list = expenses_df.groupby('Category')['Amount'].sum().reset_index().sort_values('Amount', ascending=False).to_dict(orient='records') if not expenses_df.empty and 'Category' in expenses_df.columns else []
    return render_template('reports.html', username=username, total_sales=total_sales, total_expenses=total_exp, net_profit=(total_sales - total_exp), product_summary=product_summary_list, expense_summary=expense_summary_list)

# ⚙️ 🌟 THE CLEANED SETTINGS ROUTE 🌟
@app.route('/portal/<username>/settings', methods=['GET', 'POST'])
def web_settings_tab(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: return redirect(url_for('login'))
    
    feedback_msg = None
    if request.method == 'POST' and request.form.get('action_type') == 'change_password':
        old_p, new_p = request.form.get('old_password'), request.form.get('new_password')
        conn = sqlite3.connect(USER_DB_PATH); cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE username = ?", (username,))
        if old_p == cursor.fetchone()[0]:
            cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_p, username))
            conn.commit()
            feedback_msg = "✅ Success: Your portal password has been updated!"
        else:
            feedback_msg = "❌ Error: The current password you entered is incorrect."
        conn.close()
        
    return render_template('settings.html', username=username, msg=feedback_msg)

@app.route('/logout')
def logout():
    session.pop('logged_in_user', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)