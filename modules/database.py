# modules/database.py - FULL, RESTORED WEB SQLITE VERSION WITH SUB-RECIPE INSIGHTS & AUDIT LOGGING
import pandas as pd
import sqlite3
import os
from datetime import datetime, timedelta

class InventoryDB:
    def __init__(self, db_file):
        # We are using the .db file extension for the web app
        self.db_file = db_file
        self.ensure_tables_exist()

    # ===== CORE SQLITE ENGINE =====
    def get_connection(self):
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
        return sqlite3.connect(self.db_file)

    def ensure_tables_exist(self):
        """Make sure all necessary tables exist in SQLite and run automated column migrations"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            existing_tables = [row[0] for row in cursor.fetchall()]

            default_tabs = {
                'Products': pd.DataFrame(columns=[
                    'Product_ID', 'Product_Name', 'Category', 
                    'Selling_Price', 'Active', 'Cost_Price',
                    'Profit_Margin', 'Margin_Percentage'
                ]),
                'Ingredients': pd.DataFrame(columns=[
                    'Ingredient_ID', 'Ingredient_Name', 'Unit', 
                    'Category', 'Current_Stock', 'Min_Stock', 'Cost_Per_Unit',
                    'Supplier', 'Description', 'Active', 'Last_Updated',
                    'Ingredient_Type'  # 'RAW' for stock goods, 'PREPPED' for kitchen line items
                ]),
                'Recipes': pd.DataFrame(columns=[
                    'Recipe_ID', 'Product_ID', 'Ingredient_ID', 'Quantity_Required', 'Unit'
                ]),
                'Prep_Recipes': pd.DataFrame(columns=[
                    'Prep_Recipe_ID', 'Prepped_Ingredient_ID', 'Raw_Ingredient_ID', 'Quantity_Required', 'Unit',
                    'Batch_Yield'  # Divisor tracking column factor
                ]),
                'Sales': pd.DataFrame(columns=[
                    'Sale_ID', 'Product_ID', 'Quantity', 
                    'Sale_Date', 'Sale_Time', 'Total_Amount'
                ]),
                'Inventory_Log': pd.DataFrame(columns=[
                    'Log_ID', 'Ingredient_ID', 'Change_Type', 
                    'Quantity', 'Date', 'Notes'
                ]),
                'Inventory_Audit_Log': pd.DataFrame(columns=[
                    'Audit_ID', 'Date', 'Ingredient_Name', 'Theoretical', 'Physical', 'Variance', 'Notes'
                ]),
                'Expenses': pd.DataFrame(columns=[
                    'Expense_ID', 'Expense_Date', 'Expense_Type', 
                    'Description', 'Amount', 'Category', 'Payment_Method', 'Notes'
                ]),
                'Audit_Logs': pd.DataFrame(columns=[
                    'Log_ID', 'Timestamp', 'Username', 'Action_Type', 'Module', 'Details'
                ])
            }
            
            for tab_name, df in default_tabs.items():
                if tab_name not in existing_tables:
                    df.to_sql(tab_name, conn, index=False, if_exists='replace')
                    print(f"Added missing table: {tab_name}")
            
            # SCHEMA MIGRATION 1: Ensure 'Ingredient_Type' exists inside existing databases safely
            cursor.execute("PRAGMA table_info(Ingredients);")
            columns = [row[1] for row in cursor.fetchall()]
            if 'Ingredient_Type' not in columns:
                cursor.execute("ALTER TABLE Ingredients ADD COLUMN Ingredient_Type TEXT DEFAULT 'RAW';")
                conn.commit()
                print("Schema Migration: Added 'Ingredient_Type' field safely to existing data rows.")

            # SCHEMA MIGRATION 2: Ensure 'Batch_Yield' column exists inside Prep_Recipes safely
            cursor.execute("PRAGMA table_info(Prep_Recipes);")
            prep_columns = [row[1] for row in cursor.fetchall()]
            if 'Batch_Yield' not in prep_columns:
                cursor.execute("ALTER TABLE Prep_Recipes ADD COLUMN Batch_Yield REAL DEFAULT 1.0;")
                conn.commit()
                print("Schema Migration: Added 'Batch_Yield' divisor column safely to Prep_Recipes.")

            conn.close()
        except Exception as e:
            print(f"Warning creating Database tables: {e}")

    def read_tab(self, tab_name):
        """Reads an SQLite table into a Pandas DataFrame."""
        try:
            conn = self.get_connection()
            df = pd.read_sql(f"SELECT * FROM {tab_name}", conn)
            conn.close()
            return df
        except Exception as e:
            print(f"Could not read table '{tab_name}': {e}")
            return pd.DataFrame()

    def save_tab(self, tab_name, data_df):
        """Saves a Pandas DataFrame back to SQLite."""
        try:
            conn = self.get_connection()
            data_df.to_sql(tab_name, conn, if_exists='replace', index=False)
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving table '{tab_name}': {e}")
            return False

    def is_file_locked(self, filepath):
        """SQLite handles its own locks, returning False to satisfy legacy logic"""
        return False

    # ===== AUDIT LOGGING ENGINE =====
    def log_user_action(self, username, action_type, module, details):
        """Log user actions across all app modules for accountability and security audit."""
        try:
            logs_df = self.read_tab('Audit_Logs')
            new_log = {
                'Log_ID': f"AUD{len(logs_df) + 1:06d}",
                'Timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'Username': username or 'System',
                'Action_Type': action_type,
                'Module': module,
                'Details': details
            }
            logs_df = pd.concat([logs_df, pd.DataFrame([new_log])], ignore_index=True)
            self.save_tab('Audit_Logs', logs_df)
        except Exception as e:
            print(f"Failed to record user action audit log: {e}")

    def get_audit_logs(self, limit=100, module=None, username=None):
        """Fetch recent user action audit logs with optional filtering."""
        try:
            logs_df = self.read_tab('Audit_Logs')
            if logs_df.empty:
                return pd.DataFrame()
            
            if 'Timestamp' in logs_df.columns:
                logs_df['Timestamp'] = pd.to_datetime(logs_df['Timestamp'], errors='coerce')
                logs_df = logs_df.sort_values('Timestamp', ascending=False)
            
            if module and module != 'All':
                logs_df = logs_df[logs_df['Module'] == module]
            if username and username != 'All':
                logs_df = logs_df[logs_df['Username'] == username]
                
            return logs_df.head(limit)
        except Exception as e:
            print(f"Error reading audit logs: {e}")
            return pd.DataFrame()

    # ===== BUSINESS LOGIC WITH INTEGRATED AUDIT LOGGING =====
    def add_expense(self, expense_data, username="System"):
        """Add a new expense record"""
        try:
            expenses_df = self.read_tab('Expenses')
            
            # Generate expense ID
            if expenses_df.empty:
                expense_id = "EXP0001"
            else:
                exp_numbers = []
                for exp_id in expenses_df['Expense_ID'].dropna():
                    if isinstance(exp_id, str) and exp_id.startswith('EXP'):
                        try:
                            num = int(exp_id[3:])
                            exp_numbers.append(num)
                        except:
                            pass
                
                next_num = max(exp_numbers) + 1 if exp_numbers else 1
                expense_id = f"EXP{next_num:04d}"
            
            expense_data['Expense_ID'] = expense_id
            
            new_expense_df = pd.DataFrame([expense_data])
            expenses_df = pd.concat([expenses_df, new_expense_df], ignore_index=True)
            
            self.save_tab('Expenses', expenses_df)
            
            # Record Audit Log
            self.log_user_action(
                username=username,
                action_type="ADD_EXPENSE",
                module="Expenses",
                details=f"Added Expense {expense_id}: {expense_data.get('Description', '')} (PHP {expense_data.get('Amount', 0):.2f})"
            )
            
            print(f"Added expense: {expense_data['Description']} - {expense_data['Amount']}")
            return True, f"Expense added successfully (ID: {expense_id})"
            
        except Exception as e:
            print(f"Error adding expense: {e}")
            return False, f"Error adding expense: {str(e)}"
    
    def get_expenses(self, start_date=None, end_date=None):
        """Get expenses with optional date filtering"""
        try:
            expenses_df = self.read_tab('Expenses')
            
            if expenses_df.empty:
                return pd.DataFrame()
            
            if 'Expense_Date' in expenses_df.columns:
                expenses_df['Expense_Date'] = pd.to_datetime(expenses_df['Expense_Date'])
                
                if start_date:
                    start_date = pd.to_datetime(start_date)
                    expenses_df = expenses_df[expenses_df['Expense_Date'] >= start_date]
                
                if end_date:
                    end_date = pd.to_datetime(end_date)
                    expenses_df = expenses_df[expenses_df['Expense_Date'] <= end_date]
            
            return expenses_df.sort_values('Expense_Date', ascending=False)
            
        except Exception as e:
            print(f"Error getting expenses: {e}")
            return pd.DataFrame()
    
    def get_expense_summary(self, month=None, year=None):
        """Get expense summary by category"""
        try:
            expenses_df = self.read_tab('Expenses')
            
            if expenses_df.empty:
                return pd.DataFrame()
            
            if 'Expense_Date' in expenses_df.columns:
                expenses_df['Expense_Date'] = pd.to_datetime(expenses_df['Expense_Date'])
                expenses_df['Year'] = expenses_df['Expense_Date'].dt.year
                expenses_df['Month'] = expenses_df['Expense_Date'].dt.month
                
                if year:
                    expenses_df = expenses_df[expenses_df['Year'] == year]
                if month:
                    expenses_df = expenses_df[expenses_df['Month'] == month]
            
            if 'Category' in expenses_df.columns:
                summary = expenses_df.groupby('Category').agg({
                    'Amount': ['sum', 'count']
                }).reset_index()
                
                summary.columns = ['Category', 'Total_Amount', 'Transaction_Count']
                return summary.sort_values('Total_Amount', ascending=False)
            
            return pd.DataFrame()
            
        except Exception as e:
            print(f"Error getting expense summary: {e}")
            return pd.DataFrame()
    
    def delete_expense(self, expense_id, username="System"):
        """Delete an expense record"""
        try:
            expenses_df = self.read_tab('Expenses')
            
            if expenses_df.empty:
                return False, "No expenses found"
            
            initial_count = len(expenses_df)
            deleted_rows = expenses_df[expenses_df['Expense_ID'] == expense_id]
            expenses_df = expenses_df[expenses_df['Expense_ID'] != expense_id]
            
            if len(expenses_df) == initial_count:
                return False, f"Expense {expense_id} not found"
            
            self.save_tab('Expenses', expenses_df)
            
            desc = deleted_rows.iloc[0].get('Description', '') if not deleted_rows.empty else ''
            amt = deleted_rows.iloc[0].get('Amount', 0) if not deleted_rows.empty else 0
            
            # Record Audit Log
            self.log_user_action(
                username=username,
                action_type="DELETE_EXPENSE",
                module="Expenses",
                details=f"Deleted Expense {expense_id}: {desc} (PHP {amt:.2f})"
            )
            
            print(f"Deleted expense: {expense_id}")
            return True, f"Expense {expense_id} deleted successfully"
            
        except Exception as e:
            print(f"Error deleting expense: {e}")
            return False, f"Error deleting expense: {str(e)}"
    
    def add_sale(self, product_id, quantity, unit_price, username="System"):
        """Record a new sale"""
        try:
            sales_df = self.read_tab('Sales')
            
            sale_id = f"SALE{len(sales_df) + 1:04d}"
            total_amt = quantity * unit_price
            
            new_sale = {
                'Sale_ID': sale_id,
                'Product_ID': product_id,
                'Quantity': quantity,
                'Sale_Date': datetime.now().strftime("%Y-%m-%d"),
                'Sale_Time': datetime.now().strftime("%H:%M:%S"),
                'Total_Amount': total_amt
            }
            
            sales_df = pd.concat([sales_df, pd.DataFrame([new_sale])], ignore_index=True)
            self.save_tab('Sales', sales_df)
            
            # Record Audit Log
            self.log_user_action(
                username=username,
                action_type="RECORD_SALE",
                module="Sales",
                details=f"Logged Sale {sale_id}: {quantity}x {product_id} at PHP {unit_price:.2f} each (Total: PHP {total_amt:.2f})"
            )
            
            print(f"Recorded sale: {quantity} x {product_id}")
            return new_sale
        except Exception as e:
            print(f"Error recording sale: {e}")
            return None
    
    def get_all_products(self):
        """Get all active products"""
        products_df = self.read_tab('Products')
        if products_df.empty:
            return pd.DataFrame()
        
        if 'Active' in products_df.columns:
            active_products = products_df[products_df['Active'].astype(str).str.upper() == 'YES']
        else:
            active_products = products_df
        
        return active_products
    
    def get_all_ingredients(self):
        """Get all ingredients"""
        ingredients_df = self.read_tab('Ingredients')
        return ingredients_df
    
    def get_product_recipes(self, product_id):
        """Get all ingredients for a specific product"""
        recipes_df = self.read_tab('Recipes')
        ingredients_df = self.read_tab('Ingredients')
        
        if recipes_df.empty:
            return pd.DataFrame()
        
        product_recipes = recipes_df[recipes_df['Product_ID'] == product_id].copy()
        
        if product_recipes.empty:
            return pd.DataFrame()
        
        if not ingredients_df.empty:
            merged = pd.merge(product_recipes, ingredients_df, 
                            left_on='Ingredient_ID', right_on='Ingredient_ID', 
                            how='left')
            
            cols_to_return = ['Ingredient_ID', 'Ingredient_Name', 'Quantity_Required', 'Cost_Per_Unit']
            
            if 'Unit_x' in merged.columns and 'Unit_y' in merged.columns:
                merged['Unit'] = merged['Unit_x'].fillna(merged['Unit_y'])
                cols_to_return.append('Unit')
            elif 'Unit' in merged.columns:
                cols_to_return.append('Unit')
            elif 'Unit_y' in merged.columns:
                merged['Unit'] = merged['Unit_y']
                cols_to_return.append('Unit')
                
            return merged[cols_to_return]
        else:
            return product_recipes
    
    def save_recipe(self, product_id, recipe_items, username="System"):
        """Save or update a recipe"""
        try:
            recipes_df = self.read_tab('Recipes')
            
            if not recipes_df.empty:
                recipes_df = recipes_df[recipes_df['Product_ID'] != product_id]
            
            new_records = []
            for idx, item in enumerate(recipe_items):
                new_records.append({
                    'Recipe_ID': f"{product_id}-REC{idx+1:03d}",
                    'Product_ID': product_id,
                    'Ingredient_ID': item['ingredient_id'],
                    'Quantity_Required': item['quantity'],
                    'Unit': item.get('unit', '')
                })
            
            new_df = pd.DataFrame(new_records)
            recipes_df = pd.concat([recipes_df, new_df], ignore_index=True)
            
            success = self.save_tab('Recipes', recipes_df)
            
            if success:
                self.log_user_action(
                    username=username,
                    action_type="SAVE_RECIPE",
                    module="Recipes",
                    details=f"Saved recipe specification matrix for Product {product_id} ({len(recipe_items)} line components)"
                )
                print(f"Saved recipe for {product_id} with {len(recipe_items)} ingredients")
            else:
                print(f"Failed to save recipe for {product_id}")
            
            return success
        except Exception as e:
            print(f"Error saving recipe: {e}")
            return False

    def delete_recipe(self, product_id, username="System"):
        """Removes all recipe entries for a specific product."""
        try:
            recipes_df = self.read_tab('Recipes')
            if not recipes_df.empty:
                recipes_df = recipes_df[recipes_df['Product_ID'] != product_id]
                success = self.save_tab('Recipes', recipes_df)
                
                self.log_user_action(
                    username=username,
                    action_type="DELETE_RECIPE",
                    module="Recipes",
                    details=f"Deleted recipe matrix for Product {product_id}"
                )
                
                print(f"Deleted recipe entries for {product_id}")
                return success
            return True
        except Exception as e:
            print(f"Error deleting recipe: {e}")
            return False
    
    def calculate_product_cost(self, product_id):
        """Calculate total cost of a product based on its recipe"""
        recipe_items = self.get_product_recipes(product_id)
        
        if recipe_items.empty:
            return 0.0
        
        total_cost = 0.0
        for _, item in recipe_items.iterrows():
            if 'Cost_Per_Unit' in item and 'Quantity_Required' in item:
                try:
                    cost = float(item['Cost_Per_Unit']) * float(item['Quantity_Required'])
                    total_cost += cost
                except (ValueError, TypeError):
                    pass
        
        return total_cost
    
    def update_all_product_costs(self):
        """Update costs for all products, computing sub-recipe ingredient layers first"""
        try:
            products_df = self.read_tab('Products')
            ingredients_df = self.read_tab('Ingredients')
            prep_recipes_df = self.read_tab('Prep_Recipes')

            if products_df.empty:
                return products_df
            
            if not prep_recipes_df.empty and not ingredients_df.empty:
                ingredients_df['Ingredient_ID'] = ingredients_df['Ingredient_ID'].astype(str)
                
                for idx, ing_row in ingredients_df[ingredients_df['Ingredient_Type'] == 'PREPPED'].iterrows():
                    ing_id = ing_row['Ingredient_ID']
                    formulas = prep_recipes_df[prep_recipes_df['Prepped_Ingredient_ID'] == ing_id]
                    
                    if not formulas.empty:
                        computed_prep_cost = 0.0
                        batch_yield = 1.0
                        if 'Batch_Yield' in formulas.columns:
                            try:
                                yield_val = float(formulas['Batch_Yield'].iloc[0])
                                if yield_val > 0:
                                    batch_yield = yield_val
                            except:
                                pass

                        for _, form_row in formulas.iterrows():
                            raw_id = str(form_row['Raw_Ingredient_ID'])
                            req_qty = float(form_row['Quantity_Required'] or 0.0)
                            
                            match = ingredients_df[ingredients_df['Ingredient_ID'] == raw_id]
                            if not match.empty:
                                raw_unit_cost = float(match['Cost_Per_Unit'].values[0] or 0.0)
                                computed_prep_cost += (req_qty * raw_unit_cost)
                        
                        ingredients_df.at[idx, 'Cost_Per_Unit'] = computed_prep_cost / batch_yield
                
                self.save_tab('Ingredients', ingredients_df)
            
            costs = []
            for _, product in products_df.iterrows():
                product_id = product['Product_ID']
                cost = self.calculate_product_cost(product_id)
                costs.append(cost)
            
            products_df['Cost_Price'] = costs
            
            if 'Selling_Price' in products_df.columns:
                products_df['Selling_Price'] = pd.to_numeric(products_df['Selling_Price'], errors='coerce').fillna(0.0)
                products_df['Cost_Price'] = pd.to_numeric(products_df['Cost_Price'], errors='coerce').fillna(0.0)
                
                products_df['Profit_Margin'] = products_df['Selling_Price'] - products_df['Cost_Price']
                
                products_df['Margin_Percentage'] = 0.0
                valid_sp = products_df['Selling_Price'] > 0
                products_df.loc[valid_sp, 'Margin_Percentage'] = (products_df.loc[valid_sp, 'Profit_Margin'] / products_df.loc[valid_sp, 'Selling_Price'] * 100).round(2)
            
            self.save_tab('Products', products_df)
            print(f"Recalculated costs for {len(products_df)} menu items across multi-tier production lines.")
            return products_df
        except Exception as e:
            print(f"Error updating product costs: {e}")
            return pd.DataFrame()
    
    def update_inventory_from_sale(self, product_id, quantity_sold, username="System"):
        """Deduct ingredients from inventory when a product is sold"""
        try:
            recipe_items = self.get_product_recipes(product_id)
            
            if recipe_items.empty:
                return False, f"No recipe found for product {product_id}"
            
            inventory_df = self.read_tab('Ingredients')
            if inventory_df.empty:
                return False, "No ingredients in inventory"
            
            deductions = []
            insufficient_stock = []
            
            for _, recipe_item in recipe_items.iterrows():
                ingredient_id = recipe_item['Ingredient_ID']
                quantity_needed = float(recipe_item['Quantity_Required'] or 0.0)
                total_needed = quantity_needed * float(quantity_sold)
                
                ingredient_idx = inventory_df[inventory_df['Ingredient_ID'] == ingredient_id].index
                
                if len(ingredient_idx) == 0:
                    insufficient_stock.append(f"{recipe_item.get('Ingredient_Name', ingredient_id)}: not in inventory")
                    continue
                
                idx = ingredient_idx[0]
                current_stock = float(inventory_df.at[idx, 'Current_Stock'] or 0.0)
                
                if current_stock < total_needed:
                    insufficient_stock.append(
                        f"{recipe_item.get('Ingredient_Name', ingredient_id)}: "
                        f"need {total_needed}, have {current_stock}"
                    )
                else:
                    deductions.append({
                        'ingredient_id': ingredient_id,
                        'ingredient_name': recipe_item.get('Ingredient_Name', ingredient_id),
                        'deduction': total_needed,
                        'old_stock': current_stock,
                        'new_stock': current_stock - total_needed,
                        'index': idx
                    })
            
            if insufficient_stock:
                return False, f"Insufficient stock:\n" + "\n".join(insufficient_stock)
            
            for deduction in deductions:
                idx = deduction['index']
                inventory_df.at[idx, 'Current_Stock'] = deduction['new_stock']
            
            self.save_tab('Ingredients', inventory_df)
            
            self.log_inventory_change(
                product_id=product_id,
                quantity_sold=quantity_sold,
                deductions=deductions
            )
            
            ingredient_names = [d['ingredient_name'] for d in deductions]
            return True, f"Deducted from: {', '.join(ingredient_names)}"
            
        except Exception as e:
            return False, f"Error updating inventory: {str(e)}"
    
    def delete_ingredient(self, ingredient_id, username="System"):
        """Delete an ingredient safely if unlinked to any product formula"""
        try:
            ingredients_df = self.read_tab('Ingredients')
            
            ingredient_idx = ingredients_df[ingredients_df['Ingredient_ID'] == ingredient_id].index
            
            if len(ingredient_idx) == 0:
                return False, f"Ingredient {ingredient_id} not found"
            
            idx = ingredient_idx[0]
            ing_name = ingredients_df.at[idx, 'Ingredient_Name']
            
            recipes_df = self.read_tab('Recipes')
            prep_recipes_df = self.read_tab('Prep_Recipes')
            
            if not recipes_df.empty and not recipes_df[recipes_df['Ingredient_ID'] == ingredient_id].empty:
                return False, f"Cannot delete! This ingredient is linked inside active product formulas."
            if not prep_recipes_df.empty and (not prep_recipes_df[prep_recipes_df['Raw_Ingredient_ID'] == ingredient_id].empty or not prep_recipes_df[prep_recipes_df['Prepped_Ingredient_ID'] == ingredient_id].empty):
                return False, "Cannot delete! This ingredient is linked inside active sub-recipe portion templates."
            
            ingredients_df = ingredients_df.drop(idx).reset_index(drop=True)
            
            self.save_tab('Ingredients', ingredients_df)
            
            # Record Audit Log
            self.log_user_action(
                username=username,
                action_type="DELETE_INGREDIENT",
                module="Ingredients",
                details=f"Permanently deleted ingredient {ing_name} ({ingredient_id})"
            )
            
            print(f"Deleted ingredient: {ingredient_id}")
            return True, f"Ingredient {ingredient_id} deleted successfully"
            
        except Exception as e:
            print(f"Error deleting ingredient: {e}")
            return False, f"Error deleting ingredient: {str(e)}"

    def log_inventory_change(self, product_id, quantity_sold, deductions):
        """Log inventory changes to Inventory_Log tab"""
        try:
            logs_df = self.read_tab('Inventory_Log')
            
            for deduction in deductions:
                new_log = {
                    'Log_ID': f"LOG{len(logs_df) + 1:06d}",
                    'Ingredient_ID': deduction['ingredient_id'],
                    'Change_Type': 'SALE_DEDUCTION',
                    'Quantity': -deduction['deduction'],
                    'Date': datetime.now().strftime("%Y-%m-%d"),
                    'Notes': f"Product {product_id} x{quantity_sold}"
                }
                logs_df = pd.concat([logs_df, pd.DataFrame([new_log])], ignore_index=True)
            
            self.save_tab('Inventory_Log', logs_df)
            print(f"Logged inventory change for {product_id}")
            
        except Exception as e:
            print(f"Failed to log inventory change: {e}")
    
    def add_inventory_stock(self, ingredient_id, quantity_to_add, notes="", username="System"):
        """Add stock to an ingredient (purchase/replenishment)"""
        try:
            inventory_df = self.read_tab('Ingredients')
            
            if inventory_df.empty:
                return False, "No ingredients found"
            
            ingredient_idx = inventory_df[inventory_df['Ingredient_ID'] == ingredient_id].index
            
            if len(ingredient_idx) == 0:
                return False, f"Ingredient {ingredient_id} not found"
            
            idx = ingredient_idx[0]
            old_stock = inventory_df.at[idx, 'Current_Stock']
            new_stock = old_stock + quantity_to_add
            
            inventory_df.at[idx, 'Current_Stock'] = new_stock
            self.save_tab('Ingredients', inventory_df)
            
            logs_df = self.read_tab('Inventory_Log')
            new_log = {
                'Log_ID': f"LOG{len(logs_df) + 1:06d}",
                'Ingredient_ID': ingredient_id,
                'Change_Type': 'STOCK_ADD',
                'Quantity': quantity_to_add,
                'Date': datetime.now().strftime("%Y-%m-%d"),
                'Notes': notes or f"Manual stock addition"
            }
            logs_df = pd.concat([logs_df, pd.DataFrame([new_log])], ignore_index=True)
            self.save_tab('Inventory_Log', logs_df)
            
            ingredient_name = inventory_df.at[idx, 'Ingredient_Name']
            
            # Record Audit Log
            self.log_user_action(
                username=username,
                action_type="ADD_STOCK",
                module="Ingredients",
                details=f"Injected +{quantity_to_add} stock to {ingredient_name} ({ingredient_id}). Old: {old_stock:.2f}, New: {new_stock:.2f}"
            )
            
            print(f"Added {quantity_to_add} to {ingredient_name}. New stock: {new_stock}")
            return True, f"Added {quantity_to_add} to {ingredient_name}. New stock: {new_stock}"
            
        except Exception as e:
            print(f"Error adding stock: {e}")
            return False, f"Error adding stock: {str(e)}"
    
    def get_inventory_status(self):
        """Get current inventory status with alerts"""
        inventory_df = self.read_tab('Ingredients')
        
        if inventory_df.empty:
            return pd.DataFrame()
        
        inventory_df = inventory_df.copy()
        
        if 'Min_Stock' not in inventory_df.columns:
            inventory_df['Min_Stock'] = 0
        
        inventory_df['Status'] = 'Normal'
        inventory_df['Days_Remaining'] = None
        
        low_stock_mask = pd.to_numeric(inventory_df['Current_Stock']) <= pd.to_numeric(inventory_df['Min_Stock'])
        inventory_df.loc[low_stock_mask, 'Status'] = 'Low Stock'
        
        critical_mask = pd.to_numeric(inventory_df['Current_Stock']) <= (pd.to_numeric(inventory_df['Min_Stock']) * 0.5)
        inventory_df.loc[critical_mask, 'Status'] = 'Critical'
        
        return inventory_df
    
    def get_inventory_logs(self, days_back=30):
        """Get recent inventory logs"""
        logs_df = self.read_tab('Inventory_Log')
        
        if logs_df.empty:
            return pd.DataFrame()
        
        if 'Date' in logs_df.columns:
            try:
                logs_df['Date'] = pd.to_datetime(logs_df['Date'])
                cutoff_date = datetime.now() - timedelta(days=days_back)
                recent_logs = logs_df[logs_df['Date'] >= cutoff_date].copy()
                recent_logs = recent_logs.sort_values('Date', ascending=False)
                return recent_logs
            except:
                return logs_df.tail(100)
        
        return logs_df.tail(100)
    
    def add_product(self, product_data, username="System"):
        """Add a new product to the database"""
        try:
            required_fields = ['Product_ID', 'Product_Name', 'Selling_Price', 'Active']
            for field in required_fields:
                if field not in product_data:
                    return False, f"Missing required field: {field}"
            
            products_df = self.read_tab('Products')
            
            if 'Product_ID' in products_df.columns:
                if product_data['Product_ID'] in products_df['Product_ID'].values:
                    return False, f"Product ID {product_data['Product_ID']} already exists"
            else:
                products_df['Product_ID'] = ''
            
            required_columns = ['Product_ID', 'Product_Name', 'Category', 'Selling_Price', 'Active', 
                               'Cost_Price', 'Profit_Margin', 'Margin_Percentage']
            
            for col in required_columns:
                if col not in products_df.columns:
                    products_df[col] = None
            
            new_product_row = {}
            for col in products_df.columns:
                if col in product_data:
                    new_product_row[col] = product_data[col]
                elif col == 'Cost_Price':
                    new_product_row[col] = 0.0
                elif col == 'Profit_Margin':
                    selling_price = product_data.get('Selling_Price', 0)
                    cost_price = product_data.get('Cost_Price', 0)
                    new_product_row[col] = selling_price - cost_price
                elif col == 'Margin_Percentage':
                    selling_price = product_data.get('Selling_Price', 0)
                    cost_price = product_data.get('Cost_Price', 0)
                    if selling_price > 0:
                        new_product_row[col] = ((selling_price - cost_price) / selling_price * 100)
                    else:
                        new_product_row[col] = 0.0
                else:
                    new_product_row[col] = None
            
            new_product_df = pd.DataFrame([new_product_row])
            products_df = pd.concat([products_df, new_product_df], ignore_index=True)
            
            success = self.save_tab('Products', products_df)
            
            if success:
                self.update_all_product_costs()
                
                # Record Audit Log
                self.log_user_action(
                    username=username,
                    action_type="ADD_PRODUCT",
                    module="Products",
                    details=f"Created new product {product_data['Product_Name']} ({product_data['Product_ID']}) set at Selling Price PHP {product_data['Selling_Price']:.2f}"
                )
                
                print(f"Added product: {product_data['Product_Name']} ({product_data['Product_ID']})")
                return True, f"Product '{product_data['Product_Name']}' added successfully"
            else:
                return False, "Failed to save product to database"
            
        except Exception as e:
            print(f"Error adding product: {e}")
            return False, f"Error adding product: {str(e)}"
    
    def update_product(self, product_id, updated_data, username="System"):
        """Update an existing product"""
        try:
            products_df = self.read_tab('Products')
            
            product_idx = products_df[products_df['Product_ID'] == product_id].index
            
            if len(product_idx) == 0:
                return False, f"Product {product_id} not found"
            
            idx = product_idx[0]
            old_name = products_df.at[idx, 'Product_Name']
            
            changes = []
            for key, value in updated_data.items():
                if key in products_df.columns:
                    old_val = products_df.at[idx, key]
                    if str(old_val) != str(value):
                        changes.append(f"{key}: '{old_val}' -> '{value}'")
                    products_df.at[idx, key] = value
            
            self.save_tab('Products', products_df)
            
            if changes:
                self.log_user_action(
                    username=username,
                    action_type="EDIT_PRODUCT",
                    module="Products",
                    details=f"Updated product {old_name} ({product_id}): {', '.join(changes)}"
                )
                
            print(f"Updated product: {product_id}")
            return True, f"Product {product_id} updated successfully"
            
        except Exception as e:
            print(f"Error updating product: {e}")
            return False, f"Error updating product: {str(e)}"
    
    def delete_product(self, product_id, username="System"):
        """Completely delete a product permanently from the database table (Hard Delete)"""
        try:
            products_df = self.read_tab('Products')
            
            product_idx = products_df[products_df['Product_ID'] == product_id].index
            
            if len(product_idx) == 0:
                return False, f"Product {product_id} not found"
            
            idx = product_idx[0]
            product_name = products_df.at[idx, 'Product_Name']
            
            products_df = products_df.drop(idx).reset_index(drop=True)
            self.delete_recipe(product_id, username=username)
            self.save_tab('Products', products_df)
            
            # Record Audit Log
            self.log_user_action(
                username=username,
                action_type="DELETE_PRODUCT",
                module="Products",
                details=f"Permanently deleted product {product_name} ({product_id}) and purged recipes"
            )
            
            print(f"Permanently erased product and recipe structures: {product_id}")
            return True, f"Product {product_id} completely removed from system"
            
        except Exception as e:
            print(f"Error permanently deleting product: {e}")
            return False, f"Error deleting product: {str(e)}"
    
    def add_ingredient(self, ingredient_data, username="System"):
        """Add a new ingredient to the database with unique name verification rules"""
        try:
            ingredients_df = self.read_tab('Ingredients')
            
            if 'Ingredient_Type' not in ingredient_data:
                ingredient_data['Ingredient_Type'] = 'RAW'
            
            if ingredient_data['Ingredient_ID'] in ingredients_df['Ingredient_ID'].values:
                return False, f"Ingredient ID {ingredient_data['Ingredient_ID']} already exists"
            
            if 'Ingredient_Name' in ingredients_df.columns and not ingredients_df.empty:
                existing_names = ingredients_df['Ingredient_Name'].astype(str).str.lower().str.strip().values
                new_name = str(ingredient_data['Ingredient_Name']).lower().strip()
                if new_name in existing_names:
                    return False, f"An ingredient named '{ingredient_data['Ingredient_Name']}' is already registered."
            
            new_ingredient_df = pd.DataFrame([ingredient_data])
            ingredients_df = pd.concat([ingredients_df, new_ingredient_df], ignore_index=True)
            
            self.save_tab('Ingredients', ingredients_df)
            
            # Record Audit Log
            self.log_user_action(
                username=username,
                action_type="ADD_INGREDIENT",
                module="Ingredients",
                details=f"Registered new ingredient {ingredient_data['Ingredient_Name']} ({ingredient_data['Ingredient_ID']}) [{ingredient_data.get('Ingredient_Type', 'RAW')}] Cost: PHP {ingredient_data.get('Cost_Per_Unit', 0):.2f}/{ingredient_data.get('Unit', 'pcs')}"
            )
            
            print(f"Added ingredient: {ingredient_data['Ingredient_Name']} ({ingredient_data['Ingredient_ID']})")
            return True, f"Ingredient '{ingredient_data['Ingredient_Name']}' added successfully"
            
        except Exception as e:
            print(f"Error adding ingredient: {e}")
            return False, f"Error adding ingredient: {str(e)}"
    
    def update_ingredient(self, ingredient_id, updated_data, username="System"):
        """Update an existing ingredient with modification safety name collision checks"""
        try:
            ingredients_df = self.read_tab('Ingredients')
            
            ingredient_idx = ingredients_df[ingredients_df['Ingredient_ID'] == ingredient_id].index
            
            if len(ingredient_idx) == 0:
                return False, f"Ingredient {ingredient_id} not found"
            
            idx = ingredient_idx[0]
            ing_name = ingredients_df.at[idx, 'Ingredient_Name']
            
            if 'Ingredient_Name' in updated_data and not ingredients_df.empty:
                new_name = str(updated_data['Ingredient_Name']).lower().strip()
                other_rows = ingredients_df[ingredients_df['Ingredient_ID'] != ingredient_id]
                if 'Ingredient_Name' in other_rows.columns:
                    existing_other_names = other_rows['Ingredient_Name'].astype(str).str.lower().str.strip().values
                    if new_name in existing_other_names:
                        return False, f"Cannot rename! Another ingredient named '{updated_data['Ingredient_Name']}' already exists."
            
            changes = []
            for key, value in updated_data.items():
                if key in ingredients_df.columns:
                    old_val = ingredients_df.at[idx, key]
                    if str(old_val) != str(value):
                        changes.append(f"{key}: '{old_val}' -> '{value}'")
                    ingredients_df.at[idx, key] = value
            
            self.save_tab('Ingredients', ingredients_df)
            
            if changes:
                self.log_user_action(
                    username=username,
                    action_type="EDIT_INGREDIENT",
                    module="Ingredients",
                    details=f"Updated ingredient {ing_name} ({ingredient_id}): {', '.join(changes)}"
                )
                
            print(f"Updated ingredient: {ingredient_id}")
            return True, f"Ingredient {ingredient_id} updated successfully"
            
        except Exception as e:
            print(f"Error updating ingredient: {e}")
            return False, f"Error updating ingredient: {str(e)}"
    
    def generate_product_id(self):
        """Generate a new unique product ID"""
        products_df = self.read_tab('Products')
        
        if products_df.empty:
            return "PROD001"
        
        product_ids = products_df['Product_ID'].dropna()
        prod_numbers = []
        
        for pid in product_ids:
            if isinstance(pid, str) and pid.startswith('PROD'):
                try:
                    num = int(pid[4:])
                    prod_numbers.append(num)
                except:
                    pass
        
        next_num = max(prod_numbers) + 1 if prod_numbers else 1
        return f"PROD{next_num:03d}"
    
    def generate_ingredient_id(self):
        """Generate a new unique ingredient ID"""
        ingredients_df = self.read_tab('Ingredients')
        
        if ingredients_df.empty:
            return "ING001"
        
        ingredient_ids = ingredients_df['Ingredient_ID'].dropna()
        ing_numbers = []
        
        for iid in ingredient_ids:
            if isinstance(iid, str) and iid.startswith('ING'):
                try:
                    num = int(iid[3:])
                    ing_numbers.append(num)
                except:
                    pass
        
        next_num = max(ing_numbers) + 1 if ing_numbers else 1
        return f"ING{next_num:03d}"
    
    def add_ingredient_stock(self, ingredient_id, amount, notes, username):
        """Web-app helper method to add stock and log it."""
        try:
            ingredients_df = self.read_tab('Ingredients')
            if 'Ingredient_ID' not in ingredients_df.columns:
                return False, "Ingredients table not found"
            
            idx = ingredients_df[ingredients_df['Ingredient_ID'] == ingredient_id].index
            if len(idx) == 0:
                return False, f"Ingredient {ingredient_id} not found"
            
            idx = idx[0]
            current_stock = float(ingredients_df.at[idx, 'Current_Stock'])
            ingredients_df.at[idx, 'Current_Stock'] = current_stock + amount
            self.save_tab('Ingredients', ingredients_df)
            
            logs_df = self.read_tab('Inventory_Log')
            new_log = {
                'Log_ID': f"LOG{len(logs_df) + 1:06d}",
                'Ingredient_ID': ingredient_id,
                'Change_Type': 'ADD_STOCK',
                'Quantity': amount,
                'Date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'Notes': f"{notes} | Added by: {username}"
            }
            logs_df = pd.concat([logs_df, pd.DataFrame([new_log])], ignore_index=True)
            self.save_tab('Inventory_Log', logs_df)
            
            ingredient_name = ingredients_df.at[idx, 'Ingredient_Name']
            
            self.log_user_action(
                username=username,
                action_type="ADD_STOCK",
                module="Ingredients",
                details=f"Injected +{amount} stock to {ingredient_name} ({ingredient_id}) [Note: {notes}]"
            )
            
            return True, f"Successfully added {amount} to {ingredient_id}"
        except Exception as e:
            print(f"Error in add_ingredient_stock: {e}")
            return False, str(e)