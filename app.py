# app.py - COMPLETE VERSION WITH ALL TABS RESTORED & NUMERIC FIX
from flask import Flask, redirect, session, render_template
from modules.database import InventoryDB
import sqlite3
import os
import pandas as pd  # Added to enforce number formatting

# 🌟 SYSTEM COMPONENT BLUEPRINT IMPORTS - ALL TABS RESTORED
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

# 🌟 MOUNT ALL COMPONENT BLUEPRINTS
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

# Route to automatically redirect the base URL to the dashboard
@app.route('/')
def home_redirect():
    session['logged_in_user'] = 'bakery'
    return redirect('/portal/bakery')

# The main dashboard route
@app.route('/portal/<username>')
def client_portal(username):
    username = username.lower().strip()
    
    if session.get('logged_in_user') != username: 
        session['logged_in_user'] = username

    client_db_path = f"data/client_{username}.db"
    client_db = InventoryDB(client_db_path)
    
    # Fetch Data for Dashboard
    products_df = client_db.get_all_products()
    total_products = len(products_df) if not products_df.empty else 0
    
    inventory_df = client_db.get_inventory_status()
    low_stock_count = len(inventory_df[inventory_df['Status'] == 'Low Stock']) if not inventory_df.empty else 0
    
    # Aggregating Sales Data safely as floats
    sales_df = client_db.read_tab('Sales')
    total_revenue = 0.0
    if not sales_df.empty and 'Total_Amount' in sales_df.columns:
        total_revenue = float(pd.to_numeric(sales_df['Total_Amount'], errors='coerce').fillna(0).sum())
    
    # Aggregating Expenses Data safely as floats
    expenses_df = client_db.read_tab('Expenses')
    total_expenses = 0.0
    if not expenses_df.empty and 'Amount' in expenses_df.columns:
        total_expenses = float(pd.to_numeric(expenses_df['Amount'], errors='coerce').fillna(0).sum())

    return render_template(
        'dashboard.html', username=username, total_products=total_products,
        total_revenue=total_revenue, low_stock_count=low_stock_count, total_expenses=total_expenses
    )

if __name__ == '__main__':
    app.run(debug=True)