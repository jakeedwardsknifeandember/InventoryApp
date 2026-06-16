# app.py - Production SaaS Central Controller (Fully Modular Blueprint Architecture)
from flask import Flask, redirect, session, render_template
from modules.database import InventoryDB
import sqlite3
import os

# 🌟 SYSTEM COMPONENT BLUEPRINT IMPORTS
from routes.auth import auth_bp
from routes.ingredients import ingredients_bp
from routes.products import products_bp
from routes.recipes import recipes_bp
from routes.sales import sales_bp
from routes.inventory import inventory_bp
from routes.expenses import expenses_bp
from routes.reports import reports_bp
from routes.settings import settings_bp

app = Flask(__name__)
app.secret_key = 'knife-and-ember-secret-saas-key'

# 🌟 MOUNT ALL COMPONENT BLUEPRINTS INTO ENGINE SWITCHBOARD
app.register_blueprint(auth_bp)
app.register_blueprint(ingredients_bp)
app.register_blueprint(products_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(expenses_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(settings_bp)

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

# 📊 THE CENTRAL METRIC DASHBOARD PORTAL
@app.route('/portal/<username>')
def client_portal(username):
    username = username.lower().strip()
    if session.get('logged_in_user') != username: 
        return redirect('/login')
        
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

if __name__ == '__main__':
    app.run(debug=True)