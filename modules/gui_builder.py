# modules/gui_builder.py - COMPLETE UPDATED VERSION WITH ALL MANAGEMENT FORMS
import customtkinter as ctk
import pandas as pd
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox
import os
from modules.templates import AppTemplates, DatabaseTemplates
from modules.products_gui import ProductsGUI
from modules.ingredients_gui import IngredientsGUI
from modules.recipes_gui import RecipesGUI
from modules.sales_gui import SalesGUI
from modules.inventory_gui import InventoryModuleGUI
from modules.expenses_gui import ExpensesGUI
from modules.reports_gui import ReportsGUI
from modules.settings_gui import SettingsGUI

class InventoryGUI:
    def __init__(self, window, db, config):
        self.window = window
        self.db = db
        self.config = config
        self.current_theme = ctk.get_appearance_mode()
        self.products_gui = ProductsGUI(window, db, config)
        self.ingredients_gui = IngredientsGUI(window, db, config)
        self.recipes_gui = RecipesGUI(window, db, config)
        self.sales_gui = SalesGUI(window, db, config)
        self.inventory_gui = InventoryModuleGUI(window, db, config)
        self.expenses_gui = ExpensesGUI(window, db, config)
        self.reports_gui = ReportsGUI(window, db, config)
        self.settings_gui = SettingsGUI(window, db, config)

        # Set window properties
        self.window.title(f"Inventory Manager - {config['business_name']}")
        self.window.geometry("1100x750")
        
        # Create main container
        self.create_layout()

        # Store reference to self in window for theme updates
        window.main_app = self

    def update_theme_colors(self):
        """Update all UI colors based on current theme"""
        current_theme = ctk.get_appearance_mode()
        self.current_theme = current_theme
        
        # Update sidebar background
        if hasattr(self, 'sidebar_frame'):
            if current_theme == "Dark":
                self.sidebar_frame.configure(fg_color="#2b2b2b")
            else:
                self.sidebar_frame.configure(fg_color="#f5f5f5")
            
            # Update all widgets in sidebar
            self.update_widgets_in_frame(self.sidebar_frame)
        
        # Update main content area
        if hasattr(self, 'main_content'):
            if current_theme == "Dark":
                self.main_content.configure(fg_color="#2b2b2b")
            else:
                self.main_content.configure(fg_color="#f5f5f5")
    
    def update_widgets_in_frame(self, frame):
        """Update colors of all widgets in a frame"""
        current_theme = ctk.get_appearance_mode()
        
        for widget in frame.winfo_children():
            try:
                if isinstance(widget, ctk.CTkLabel):
                    if current_theme == "Dark":
                        widget.configure(text_color="#f0f0f0")
                    else:
                        widget.configure(text_color="#2c2c2c")
                
                elif isinstance(widget, ctk.CTkButton):
                    current_color = widget.cget("fg_color")
                    # Don't change special colored buttons
                    if current_color not in ["#27ae60", "#e74c3c", "#3498db", "#9b59b6", "#f39c12"]:
                        if current_theme == "Dark":
                            widget.configure(text_color="#f0f0f0")
                        else:
                            widget.configure(text_color="#2c2c2c")
                
                # Recursively update child frames
                if isinstance(widget, ctk.CTkFrame):
                    self.update_widgets_in_frame(widget)
                    
            except:
                pass  # Skip widgets that don't support color changes
    
    def create_layout(self):
        """Create the main layout with sidebar and main area"""
        
        # Create sidebar
        self.sidebar = ctk.CTkFrame(self.window, width=220, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        
        # Create main content area
        self.main_content = ctk.CTkFrame(self.window, corner_radius=0)
        self.main_content.pack(side="right", expand=True, fill="both")
        
        # Add sidebar buttons
        self.create_sidebar_buttons()
        
        # Start with dashboard
        self.show_dashboard()
    
    def create_sidebar_buttons(self):
        """Create navigation buttons in sidebar"""
        
        # Logo/title area
        title = ctk.CTkLabel(self.sidebar, text="INVENTORY", 
                            font=("Arial", 22, "bold"),
                            text_color=("gray10", "gray90"))
        title.pack(pady=(20, 10))
        
        sub_title = ctk.CTkLabel(self.sidebar, 
                                text=f"{self.config['business_name']}",
                                font=("Arial", 12),
                                text_color=("gray10", "gray90"))
        sub_title.pack(pady=(0, 20))
        
        # Navigation buttons - FIXED INDENTATION AND SYNTAX
        buttons = [
            ("📊 Dashboard", self.show_dashboard),
            ("🏪 Products", lambda: self.products_gui.show_products_management(self.main_content)),
            ("🥚 Ingredients", lambda: self.ingredients_gui.show_ingredients_management(self.main_content)),
            ("📝 Recipes", lambda: self.recipes_gui.show_recipes(self.main_content)),
            ("💰 Sales", lambda: self.sales_gui.show_sales(self.main_content)),
            ("📦 Inventory", lambda: self.inventory_gui.show_inventory(self.main_content)),
            ("💸 Expenses", lambda: self.expenses_gui.show_expenses_management(self.main_content)),
            ("📈 Reports", lambda: self.reports_gui.show_reports(self.main_content)),
            ("⚙️ Settings", lambda: self.settings_gui.show_settings(self.main_content)),
        ]
        
        for text, command in buttons:
            btn = ctk.CTkButton(self.sidebar, text=text, 
                               command=command,
                               height=40,
                               font=("Arial", 13),
                               fg_color="transparent",
                               text_color=("gray10", "gray90"),
                               hover_color="#2b7cff",
                               anchor="w")
            btn.pack(fill="x", padx=10, pady=3)
        
        # Separator
        ctk.CTkLabel(self.sidebar, text="", height=20).pack()
        
        # Exit button at bottom
        ctk.CTkButton(self.sidebar, text="🚪 Exit", 
                     command=self.window.destroy,
                     fg_color="#e74c3c", 
                     hover_color="#c0392b",
                     height=40).pack(side="bottom", pady=20, padx=10)
    
    def clear_main_content(self):
        """Clear the main content area"""
        for widget in self.main_content.winfo_children():
            widget.destroy()
    
    def show_dashboard(self):
        """Show dashboard with summary"""
        self.clear_main_content()
        
        # Title
        title = ctk.CTkLabel(self.main_content, text="Dashboard", 
                            font=("Arial", 28, "bold"))
        title.pack(pady=20)
        
        # Create frames for stats
        stats_frame = ctk.CTkFrame(self.main_content)
        stats_frame.pack(pady=10, padx=20, fill="x")
        
        # Get data
        products_df = self.db.get_all_products()
        sales_df = self.db.read_tab('Sales')
        inventory_df = self.db.get_inventory_status()
        
        # Calculate stats
        total_products = len(products_df) if not products_df.empty else 0
        
        today = datetime.now().strftime(self.config['date_format'])
        total_sales_today = 0
        if not sales_df.empty and 'Sale_Date' in sales_df.columns and 'Total_Amount' in sales_df.columns:
            today_sales = sales_df[sales_df['Sale_Date'] == today]
            total_sales_today = today_sales['Total_Amount'].sum() if not today_sales.empty else 0
        
        # Check low stock
        low_stock_count = 0
        critical_count = 0
        if not inventory_df.empty and 'Status' in inventory_df.columns:
            low_stock_count = len(inventory_df[inventory_df['Status'] == 'Low Stock'])
            critical_count = len(inventory_df[inventory_df['Status'] == 'Critical'])
        
        # Display stats in a grid
        stats_grid = ctk.CTkFrame(stats_frame)
        stats_grid.pack(pady=20, padx=20)
        
        stats_data = [
            ("Total Products", f"{total_products}", "#3498db"),
            ("Today's Sales", f"{self.config['currency']}{total_sales_today:,.2f}", "#27ae60"),
            ("Low Stock Items", f"{low_stock_count}", "#f39c12" if low_stock_count > 0 else "#95a5a6"),
            ("Critical Items", f"{critical_count}", "#e74c3c" if critical_count > 0 else "#95a5a6")
        ]
        
        row = 0
        col = 0
        for stat_name, stat_value, color in stats_data:
            stat_frame = ctk.CTkFrame(stats_grid, width=220, height=100, 
                                    corner_radius=15, fg_color=color)
            stat_frame.grid(row=row, column=col, padx=10, pady=10)
            stat_frame.pack_propagate(False)
            
            ctk.CTkLabel(stat_frame, text=stat_name, 
                        font=("Arial", 14),
                        text_color="white").pack(pady=(15, 5))
            ctk.CTkLabel(stat_frame, text=stat_value, 
                        font=("Arial", 22, "bold"),
                        text_color="white").pack()
            
            col += 1
            if col > 1:  # 2 columns per row
                col = 0
                row += 1
        
        # Inventory alerts section
        if low_stock_count > 0 or critical_count > 0:
            alerts_frame = ctk.CTkFrame(self.main_content, border_width=2, 
                                       border_color="#e74c3c", corner_radius=10)
            alerts_frame.pack(pady=20, padx=20, fill="x")
            
            alert_text = f"⚠️  ALERT: {critical_count} Critical, {low_stock_count} Low Stock Items"
            ctk.CTkLabel(alerts_frame, 
                        text=alert_text,
                        font=("Arial", 14, "bold"),
                        text_color="#e74c3c").pack(pady=10)
            
            # Show critical items
            if critical_count > 0:
                critical_items = inventory_df[inventory_df['Status'] == 'Critical']
                for _, item in critical_items.head(3).iterrows():  # Show top 3
                    item_text = f"• {item['Ingredient_Name']}: {item['Current_Stock']} left (Min: {item['Min_Stock']})"
                    ctk.CTkLabel(alerts_frame,
                                text=item_text,
                                text_color="#e74c3c").pack(anchor="w", padx=30, pady=2)
            
            ctk.CTkButton(alerts_frame, text="View All Alerts",
                         command=self.show_inventory,
                         fg_color="#e74c3c", 
                         hover_color="#c0392b",
                         height=35).pack(pady=10)
        
        # Quick actions
        ctk.CTkLabel(self.main_content, text="Quick Actions", 
                    font=("Arial", 20, "bold")).pack(pady=(30, 15))
        
        actions_frame = ctk.CTkFrame(self.main_content)
        actions_frame.pack(pady=10, padx=20)
        
        action_buttons = [
            ("➕ New Product", lambda: self.products_gui.show_products_management(self.main_content), "#3498db"),
            ("🥚 Add Ingredient", lambda: self.ingredients_gui.show_ingredients_management(self.main_content), "#9b59b6"),
            ("💰 New Sale", lambda: self.sales_gui.show_sales(self.main_content), "#27ae60"),
            ("📦 Check Inventory", lambda: self.inventory_gui.show_inventory(self.main_content), "#f39c12"),
        ]
        
        for btn_text, command, color in action_buttons:
            btn = ctk.CTkButton(actions_frame, text=btn_text,
                               command=command,
                               fg_color=color, 
                               hover_color=self.darken_color(color),
                               height=45,
                               font=("Arial", 13))
            btn.pack(side="left", padx=10, pady=10)
        
        # Popular Products Section
        ctk.CTkLabel(self.main_content, text="🔥 Popular Products (Last 7 Days)", 
                    font=("Arial", 18, "bold")).pack(pady=(30, 15))
        
        popular_frame = ctk.CTkFrame(self.main_content)
        popular_frame.pack(pady=10, padx=20, fill="x")
        
        popular_products = self.get_popular_products()
        
        if not popular_products.empty:
            # Create a simple table for popular products
            headers_frame = ctk.CTkFrame(popular_frame, fg_color="transparent")
            headers_frame.pack(fill="x", padx=10, pady=5)
            
            headers = ["Product", "Quantity Sold", "Revenue"]
            for i, header in enumerate(headers):
                ctk.CTkLabel(headers_frame, text=header, 
                            font=("Arial", 12, "bold"),
                            width=150 if i == 0 else 120).pack(side="left", padx=10)
            
            for _, product in popular_products.iterrows():
                row_frame = ctk.CTkFrame(popular_frame, fg_color="transparent")
                row_frame.pack(fill="x", padx=10, pady=5)
                
                ctk.CTkLabel(row_frame, text=product['Product_Name'][:30], 
                            width=150).pack(side="left", padx=10)
                ctk.CTkLabel(row_frame, text=f"{product['Quantity']:,.0f}", 
                            width=120).pack(side="left", padx=10)
                ctk.CTkLabel(row_frame, text=f"{self.config['currency']}{product['Total_Amount']:,.2f}", 
                            width=120, text_color="green").pack(side="left", padx=10)
        else:
            ctk.CTkLabel(popular_frame, text="No recent sales data",
                        font=("Arial", 12), text_color="gray").pack(pady=20)
        
        # Quick Inventory Status
        ctk.CTkLabel(self.main_content, text="📦 Quick Inventory Status", 
                    font=("Arial", 18, "bold")).pack(pady=(30, 15))
        
        quick_inv_frame = ctk.CTkFrame(self.main_content)
        quick_inv_frame.pack(pady=10, padx=20, fill="x")
        
        inventory_status = self.db.get_inventory_status()
        
        if not inventory_status.empty:
            # Get top 5 critical/low stock items
            critical_items = inventory_status[inventory_status['Status'] == 'Critical'].head(3)
            low_items = inventory_status[inventory_status['Status'] == 'Low Stock'].head(3)
            
            if not critical_items.empty:
                ctk.CTkLabel(quick_inv_frame, text="🚨 Critical Stock:",
                            font=("Arial", 14, "bold"), text_color="#e74c3c").pack(anchor="w", padx=20, pady=(10, 5))
                
                for _, item in critical_items.iterrows():
                    item_text = f"• {item['Ingredient_Name']}: {item['Current_Stock']} left (Min: {item['Min_Stock']})"
                    ctk.CTkLabel(quick_inv_frame, text=item_text,
                                text_color="#e74c3c").pack(anchor="w", padx=40, pady=2)
            
            if not low_items.empty:
                ctk.CTkLabel(quick_inv_frame, text="⚠️ Low Stock:",
                            font=("Arial", 14, "bold"), text_color="#f39c12").pack(anchor="w", padx=20, pady=(10, 5))
                
                for _, item in low_items.iterrows():
                    item_text = f"• {item['Ingredient_Name']}: {item['Current_Stock']} left (Min: {item['Min_Stock']})"
                    ctk.CTkLabel(quick_inv_frame, text=item_text,
                                text_color="#f39c12").pack(anchor="w", padx=40, pady=2)
            
            if critical_items.empty and low_items.empty:
                ctk.CTkLabel(quick_inv_frame, text="✅ All inventory levels are normal",
                            text_color="green").pack(pady=20)
        else:
            ctk.CTkLabel(quick_inv_frame, text="No inventory data available",
                        font=("Arial", 12), text_color="gray").pack(pady=20)    
    def darken_color(self, hex_color):
        """Darken a hex color for hover effect"""
        # Simple darkening - you can implement more sophisticated color manipulation
        return hex_color
    
    def get_popular_products(self, days_back=7):
        """Get popular products from recent sales"""
        try:
            sales_df = self.db.read_tab('Sales')
            products_df = self.db.read_tab('Products')
            
            if sales_df.empty or products_df.empty:
                return pd.DataFrame()
            
            # Filter recent sales
            cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            recent_sales = sales_df[sales_df['Sale_Date'] >= cutoff_date]
            
            if recent_sales.empty:
                return pd.DataFrame()
            
            # Group by product
            product_sales = recent_sales.groupby('Product_ID').agg({
                'Quantity': 'sum',
                'Total_Amount': 'sum'
            }).reset_index()
            
            # Get product names
            product_sales = pd.merge(product_sales, products_df[['Product_ID', 'Product_Name']], 
                                    on='Product_ID', how='left')
            
            return product_sales.sort_values('Quantity', ascending=False).head(5)
        except:
            return pd.DataFrame()
    
    def show_settings(self):
        """Show settings interface"""
        self.clear_main_content()
        
        # Create tabview for settings
        settings_tabs = ctk.CTkTabview(self.main_content)
        settings_tabs.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Add tabs
        settings_tabs.add("Business Info")
        settings_tabs.add("Preferences")
        settings_tabs.add("Data Management")
        settings_tabs.add("About")
        
        # Fill each tab
        self.show_business_settings(settings_tabs.tab("Business Info"))
        self.show_preferences_settings(settings_tabs.tab("Preferences"))
        self.show_data_management(settings_tabs.tab("Data Management"))
        self.show_about_info(settings_tabs.tab("About"))
    
    def show_business_settings(self, parent_frame):
        """Show business information settings"""
        ctk.CTkLabel(parent_frame, text="Business Information", 
                    font=("Arial", 22, "bold")).pack(pady=10)
        
        # Form frame
        form_frame = ctk.CTkFrame(parent_frame)
        form_frame.pack(pady=20, padx=50, fill="x")
        
        # Current business info
        current_info = f"Current Business: {self.config['business_name']}"
        ctk.CTkLabel(form_frame, text=current_info, 
                    font=("Arial", 14, "bold")).pack(pady=10)
        
        # Form fields
        fields = [
            ("Business Name:", "business_name", self.config['business_name']),
            ("Currency Symbol:", "currency", self.config['currency']),
            ("Date Format:", "date_format", self.config['date_format']),
            ("Low Stock Warning Level:", "low_stock_warning", str(self.config['low_stock_warning']))
        ]
        
        self.settings_entries = {}
        
        for label_text, field_name, default_value in fields:
            row_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=10)
            
            ctk.CTkLabel(row_frame, text=label_text, 
                        width=150, anchor="w").pack(side="left", padx=10)
            
            entry = ctk.CTkEntry(row_frame, width=250)
            entry.insert(0, default_value)
            entry.pack(side="left", padx=10)
            
            self.settings_entries[field_name] = entry
        
        # Tax rate setting
        tax_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        tax_frame.pack(fill="x", pady=10)
        
        ctk.CTkLabel(tax_frame, text="Tax Rate (%):", 
                    width=150, anchor="w").pack(side="left", padx=10)
        
        self.tax_rate_var = tk.StringVar(value="12.0")  # Default 12%
        tax_entry = ctk.CTkEntry(tax_frame, textvariable=self.tax_rate_var, width=250)
        tax_entry.pack(side="left", padx=10)
        
        # Business address
        address_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        address_frame.pack(fill="x", pady=10)
        
        ctk.CTkLabel(address_frame, text="Business Address:", 
                    width=150, anchor="w").pack(side="left", padx=10)
        
        self.address_text = ctk.CTkTextbox(address_frame, width=250, height=80)
        self.address_text.pack(side="left", padx=10)
        self.address_text.insert("1.0", "123 Business Street\nCity, Country")  # Default
        
        # Save button
        button_frame = ctk.CTkFrame(parent_frame)
        button_frame.pack(pady=20)
        
        ctk.CTkButton(button_frame, text="💾 Save Settings",
                     command=self.save_business_settings,
                     fg_color="#27ae60", hover_color="#219653",
                     width=150, height=40).pack(side="left", padx=10)
        
        ctk.CTkButton(button_frame, text="Reset to Defaults",
                     command=self.reset_settings,
                     width=150, height=40).pack(side="left", padx=10)
        
        # Status label
        self.settings_status_label = ctk.CTkLabel(parent_frame, text="", 
                                                 font=("Arial", 12))
        self.settings_status_label.pack(pady=10)
    
    def save_business_settings(self):
        """Save business settings"""
        try:
            # Update config
            new_config = {}
            
            for field_name, entry in self.settings_entries.items():
                new_config[field_name] = entry.get()
            
            # Update tax rate
            try:
                tax_rate = float(self.tax_rate_var.get())
                # You might want to save this somewhere
            except:
                pass
            
            # Update business address
            address = self.address_text.get("1.0", "end-1c").strip()
            
            # For now, just update the current session
            self.config.update(new_config)
            
            # Update window title
            self.window.title(f"Inventory Manager - {self.config['business_name']}")
            
            self.settings_status_label.configure(
                text="✅ Settings saved (session only).\nRestart app to update config file.",
                text_color="green"
            )
            
        except Exception as e:
            self.settings_status_label.configure(
                text=f"❌ Error saving settings: {str(e)}",
                text_color="red"
            )
    
    def reset_settings(self):
        """Reset settings to defaults"""
        confirm = messagebox.askyesno("Reset Settings", 
                                     "Reset all settings to defaults?")
        if confirm:
            # Reset form fields
            defaults = {
                'business_name': "My Bakery Shop",
                'currency': "₱",
                'date_format': "%Y-%m-%d",
                'low_stock_warning': "20"
            }
            
            for field_name, default_value in defaults.items():
                if field_name in self.settings_entries:
                    self.settings_entries[field_name].delete(0, 'end')
                    self.settings_entries[field_name].insert(0, default_value)
            
            self.tax_rate_var.set("12.0")
            self.address_text.delete("1.0", "end")
            self.address_text.insert("1.0", "123 Business Street\nCity, Country")
            
            self.settings_status_label.configure(
                text="✅ Settings reset to defaults",
                text_color="green"
            )
    
    def show_preferences_settings(self, parent_frame):
        """Show application preferences"""
        ctk.CTkLabel(parent_frame, text="Application Preferences", 
                    font=("Arial", 22, "bold")).pack(pady=10)
        
        # Theme selection
        theme_frame = ctk.CTkFrame(parent_frame)
        theme_frame.pack(pady=20, padx=50, fill="x")
        
        ctk.CTkLabel(theme_frame, text="Theme:", 
                    font=("Arial", 14)).pack(pady=10)
        
        self.theme_var = tk.StringVar(value="System")
        theme_menu = ctk.CTkOptionMenu(theme_frame,
                                      values=["System", "Light", "Dark"],
                                      variable=self.theme_var,
                                      width=200)
        theme_menu.pack(pady=10)
        
        # Apply theme button - FIXED: Now updates the sidebar colors
        ctk.CTkButton(theme_frame, text="Apply Theme",
                     command=self.apply_theme,
                     width=150).pack(pady=10)
        
        # Default units
        units_frame = ctk.CTkFrame(parent_frame)
        units_frame.pack(pady=20, padx=50, fill="x")
        
        ctk.CTkLabel(units_frame, text="Default Units:", 
                    font=("Arial", 14)).pack(pady=10)
        
        # Weight units
        weight_frame = ctk.CTkFrame(units_frame, fg_color="transparent")
        weight_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(weight_frame, text="Weight:", width=80).pack(side="left", padx=10)
        self.weight_unit_var = tk.StringVar(value="g")
        weight_menu = ctk.CTkOptionMenu(weight_frame,
                                       values=["g", "kg", "mg"],
                                       variable=self.weight_unit_var,
                                       width=100)
        weight_menu.pack(side="left", padx=10)
        
        # Volume units
        volume_frame = ctk.CTkFrame(units_frame, fg_color="transparent")
        volume_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(volume_frame, text="Volume:", width=80).pack(side="left", padx=10)
        self.volume_unit_var = tk.StringVar(value="ml")
        volume_menu = ctk.CTkOptionMenu(volume_frame,
                                       values=["ml", "L"],
                                       variable=self.volume_unit_var,
                                       width=100)
        volume_menu.pack(side="left", padx=10)
        
        # Save preferences
        ctk.CTkButton(parent_frame, text="💾 Save Preferences",
                     command=self.save_preferences,
                     fg_color="#27ae60", hover_color="#219653",
                     width=200, height=40).pack(pady=20)
    
    def apply_theme(self):
        """Apply selected theme - UPDATED to fix sidebar colors"""
        theme = self.theme_var.get()
        ctk.set_appearance_mode(theme)
        
        # Update the sidebar colors immediately
        self.update_theme_colors()
        
        messagebox.showinfo("Theme Applied", f"Theme changed to {theme} mode.")
    
    def save_preferences(self):
        """Save application preferences"""
        messagebox.showinfo("Preferences", 
                          "Preferences saved!\n\n"
                          f"Theme: {self.theme_var.get()}\n"
                          f"Default Weight Unit: {self.weight_unit_var.get()}\n"
                          f"Default Volume Unit: {self.volume_unit_var.get()}")
    
    def show_data_management(self, parent_frame):
        """Show data management options"""
        ctk.CTkLabel(parent_frame, text="Data Management", 
                    font=("Arial", 22, "bold")).pack(pady=10)
        
        # Warning frame
        warning_frame = ctk.CTkFrame(parent_frame, border_width=2, 
                                    border_color="#e74c3c", corner_radius=10)
        warning_frame.pack(pady=20, padx=50, fill="x")
        
        ctk.CTkLabel(warning_frame, text="⚠️ IMPORTANT WARNING", 
                    font=("Arial", 16, "bold"),
                    text_color="#e74c3c").pack(pady=10)
        
        warning_text = "• ALWAYS close Excel before these operations\n"
        warning_text += "• Make sure you have backups\n"
        warning_text += "• Some actions cannot be undone!"
        
        ctk.CTkLabel(warning_frame, text=warning_text,
                    text_color="#e74c3c").pack(pady=10)
        
        # Data management buttons
        actions_frame = ctk.CTkFrame(parent_frame)
        actions_frame.pack(pady=20, padx=50, fill="both", expand=True)
        
        action_buttons = [
            ("💾 Backup All Data", self.export_all_data, "#3498db"),
            ("🗑️ Clear All Data (Safe)", self.clear_all_data_with_backup, "#e74c3c"),
            ("🔄 Recalculate All Costs", self.recalculate_costs, "#9b59b6"),
            ("🔍 Check File Status", self.check_file_status, "#f39c12")
        ]
        
        for btn_text, command, color in action_buttons:
            btn = ctk.CTkButton(actions_frame, text=btn_text,
                               command=command,
                               fg_color=color,
                               hover_color=self.darken_color(color),
                               height=45,
                               font=("Arial", 13))
            btn.pack(pady=10, fill="x")

    def check_file_status(self):
        """Check if the database file is accessible"""
        import os
        
        filepath = self.db.excel_file
        
        if not os.path.exists(filepath):
            messagebox.showinfo("File Status", "Database file not found!")
            return
        
        try:
            # Try to read the file
            test_df = pd.read_excel(filepath, sheet_name=0, nrows=1)
            
            # Try to write to the file
            with open(filepath, 'a') as f:
                pass
            
            file_size = os.path.getsize(filepath)
            size_kb = file_size / 1024
            
            status_msg = f"✅ Database File Status:\n\n"
            status_msg += f"File: {filepath}\n"
            status_msg += f"Size: {size_kb:.1f} KB\n"
            status_msg += f"Access: Read/Write OK\n"
            status_msg += f"Status: READY TO USE\n\n"
            status_msg += "Tip: Close Excel before making changes."
            
            messagebox.showinfo("File Status - OK", status_msg)
            
        except PermissionError:
            messagebox.showerror("File Status - LOCKED", 
                               "❌ Database file is LOCKED!\n\n"
                               "The file cannot be accessed because:\n"
                               "1. It's open in Microsoft Excel\n"
                               "2. Another program is using it\n"
                               "3. You don't have permission\n\n"
                               "SOLUTION: Close Excel and try again.")
            
        except Exception as e:
            messagebox.showerror("File Status - ERROR", 
                               f"❌ Cannot access database file:\n\n{str(e)}")
    
    def reset_demo_data(self):
        """Reset to demo data"""
        confirm = messagebox.askyesno("Reset Demo Data", 
                                     "Replace all data with demo data?\n\n"
                                     "This will delete your current data!")
        if confirm:
            try:
                # Create demo data
                demo_file = "data/inventory_demo.xlsx"
                
                # Copy the demo creation logic from database.py
                messagebox.showinfo("Demo Data", 
                                  "Demo data reset feature coming soon!\n"
                                  "For now, delete your inventory.xlsx file and restart the app.")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to reset demo data: {str(e)}")
    
    def clear_all_data(self):
        """Clear all data - WORKING VERSION"""
        confirm = messagebox.askyesno("Clear All Data", 
                                     "⚠️ DELETE ALL DATA? ⚠️\n\n"
                                     "This will remove ALL records from:\n"
                                     "• Products\n• Ingredients\n• Recipes\n• Sales\n• Inventory Logs\n\n"
                                     "Make sure you have exported backups first!")
        
        if not confirm:
            return
        
        confirm2 = messagebox.askyesno("FINAL WARNING", 
                                      "🚨 ARE YOU ABSOLUTELY SURE? 🚨\n\n"
                                      "This action CANNOT BE UNDONE!\n"
                                      "All your data will be permanently deleted.\n\n"
                                      "Type 'DELETE' in the next box to confirm.")
        
        if not confirm2:
            return
        
        # Final confirmation with text input
        from tkinter import simpledialog
        user_input = simpledialog.askstring("Final Confirmation", 
                                          "Type DELETE to confirm permanent deletion:")
        
        if user_input != "DELETE":
            messagebox.showinfo("Cancelled", "Data deletion cancelled.")
            return
        
        try:
            # Show progress
            progress_window = ctk.CTkToplevel(self.window)
            progress_window.title("Clearing Data...")
            progress_window.geometry("400x200")
            progress_window.transient(self.window)
            progress_window.grab_set()
            
            # Center the window
            progress_window.update_idletasks()
            x = self.window.winfo_x() + (self.window.winfo_width() - progress_window.winfo_width()) // 2
            y = self.window.winfo_y() + (self.window.winfo_height() - progress_window.winfo_height()) // 2
            progress_window.geometry(f"+{x}+{y}")
            
            ctk.CTkLabel(progress_window, text="🗑️ Clearing all data...", 
                        font=("Arial", 16, "bold")).pack(pady=20)
            
            progress_label = ctk.CTkLabel(progress_window, text="Starting...")
            progress_label.pack(pady=10)
            
            # Update progress
            progress_window.update()
            
            # Define the exact column structure for each tab
            tab_structures = {
                'Products': ['Product_ID', 'Product_Name', 'Category', 
                            'Selling_Price', 'Active', 'Cost_Price',
                            'Profit_Margin', 'Margin_Percentage', 'Notes'],
                
                'Ingredients': ['Ingredient_ID', 'Ingredient_Name', 'Unit', 
                               'Category', 'Current_Stock', 'Min_Stock', 
                               'Cost_Per_Unit', 'Notes'],
                
                'Recipes': ['Recipe_ID', 'Product_ID', 'Ingredient_ID', 'Quantity_Required'],
                
                'Sales': ['Sale_ID', 'Product_ID', 'Quantity', 
                         'Sale_Date', 'Sale_Time', 'Total_Amount'],
                
                'Inventory_Log': ['Log_ID', 'Ingredient_ID', 'Change_Type', 
                                 'Quantity', 'Date', 'Notes']
            }
            
            # Clear each tab
            for i, (tab_name, columns) in enumerate(tab_structures.items(), 1):
                progress_label.configure(text=f"Clearing {tab_name}... ({i}/5)")
                progress_window.update()
                
                # Create empty DataFrame with correct columns
                empty_df = pd.DataFrame(columns=columns)
                
                # Save to database
                self.db.save_tab(tab_name, empty_df)
                
                # Small delay to show progress
                progress_window.after(100)
            
            # Close progress window
            progress_window.destroy()
            
            # Force reload the database
            self.db.__init__(self.db.excel_file)
            
            # Show success message
            messagebox.showinfo("✅ Success", 
                              "All data has been successfully cleared!\n\n"
                              "Database structure preserved.\n"
                              "You can now start fresh.")
            
            # Refresh current view if applicable
            current_method = getattr(self, 'clear_main_content', None)
            if current_method:
                current_method()
                ctk.CTkLabel(self.main_content, text="✅ Database cleared successfully!", 
                           font=("Arial", 16, "bold")).pack(pady=50)
            
        except Exception as e:
            error_msg = f"❌ Error clearing data:\n\n{str(e)}"
            print(error_msg)
            messagebox.showerror("Error", error_msg)
    
    def recalculate_costs(self):
        """Recalculate all product costs"""
        try:
            products_df = self.db.update_all_product_costs()
            messagebox.showinfo("Costs Recalculated", 
                              f"Recalculated costs for {len(products_df)} products.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to recalculate costs: {str(e)}")

    def clear_all_data_with_backup(self):
        """Clear all data with automatic backup"""
        import shutil
        from datetime import datetime
        
        # Check if file is locked first
        if hasattr(self.db, 'is_file_locked'):
            if self.db.is_file_locked(self.db.excel_file):
                messagebox.showerror("File Locked", 
                                   "❌ Cannot clear data!\n\n"
                                   "The Excel file is locked by another program.\n"
                                   "Please close Excel and try again.")
                return
        
        confirm = messagebox.askyesno("Clear All Data", 
                                     "This will:\n\n"
                                     "1. Create a backup of your current data\n"
                                     "2. Clear all data from the database\n"
                                     "3. Preserve the database structure\n\n"
                                     "Continue?")
        
        if not confirm:
            return
        
        try:
            # Create backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = f"data/backup_{timestamp}.xlsx"
            shutil.copy2(self.db.excel_file, backup_file)
            
            print(f"📦 Backup created: {backup_file}")
            
            # Now clear the data
            tab_structures = {
                'Products': ['Product_ID', 'Product_Name', 'Category', 
                            'Selling_Price', 'Active', 'Cost_Price',
                            'Profit_Margin', 'Margin_Percentage', 'Notes'],
                
                'Ingredients': ['Ingredient_ID', 'Ingredient_Name', 'Unit', 
                               'Category', 'Current_Stock', 'Min_Stock', 
                               'Cost_Per_Unit', 'Notes'],
                
                'Recipes': ['Recipe_ID', 'Product_ID', 'Ingredient_ID', 'Quantity_Required'],
                
                'Sales': ['Sale_ID', 'Product_ID', 'Quantity', 
                         'Sale_Date', 'Sale_Time', 'Total_Amount'],
                
                'Inventory_Log': ['Log_ID', 'Ingredient_ID', 'Change_Type', 
                                 'Quantity', 'Date', 'Notes']
            }
            
            # Clear each tab
            for tab_name, columns in tab_structures.items():
                empty_df = pd.DataFrame(columns=columns)
                self.db.save_tab(tab_name, empty_df)
            
            messagebox.showinfo("✅ Success", 
                              f"All data cleared successfully!\n\n"
                              f"Backup saved as:\n{backup_file}\n\n"
                              "You can now start with a fresh database.")
            
        except PermissionError:
            messagebox.showerror("Permission Error", 
                               "Cannot access the Excel file.\n"
                               "Please make sure:\n"
                               "1. Excel is closed\n"
                               "2. You have write permissions\n"
                               "3. File is not read-only")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear data: {str(e)}")
    
    def show_about_info(self, parent_frame):
        """Show about information"""
        ctk.CTkLabel(parent_frame, text="About Inventory Manager", 
                    font=("Arial", 22, "bold")).pack(pady=10)
        
        # Info frame
        info_frame = ctk.CTkFrame(parent_frame)
        info_frame.pack(pady=20, padx=50, fill="both", expand=True)
        
        about_text = f"""
Inventory Management System
Version 1.0

📊 Features:
• Product Management
• Ingredient Tracking
• Recipe Costing
• Sales Processing
• Inventory Management
• Comprehensive Reporting
• Data Export

📁 Data Storage:
• Excel-based database
• Automatic backups
• Easy data export

⚙️ Technology:
• Python 3.x
• CustomTkinter GUI
• Pandas for data handling
• Openpyxl for Excel operations

Developed for small businesses
to manage inventory efficiently.

For support or feature requests,
please contact your developer.

💡 Tip: Always backup your data regularly!
"""
        
        ctk.CTkLabel(info_frame, text=about_text,
                    font=("Arial", 11),
                    justify="left").pack(pady=20, padx=20)
        
        # System info
        sys_frame = ctk.CTkFrame(parent_frame)
        sys_frame.pack(pady=10, padx=50, fill="x")
        
        import os
        import sys
        
        sys_info = f"""
System Information:
• Python: {sys.version.split()[0]}
• Database: {self.config['excel_file']}
• File Size: {self.get_file_size(self.config['excel_file'])}
• Working Directory: {os.getcwd()}
"""
        
        ctk.CTkLabel(sys_frame, text=sys_info,
                    font=("Arial", 10),
                    justify="left").pack(pady=10, padx=10)
    
    def get_file_size(self, filepath):
        """Get file size in readable format"""
        try:
            if os.path.exists(filepath):
                size = os.path.getsize(filepath)
                # Convert to KB/MB
                if size < 1024:
                    return f"{size} bytes"
                elif size < 1024 * 1024:
                    return f"{size/1024:.1f} KB"
                else:
                    return f"{size/(1024*1024):.1f} MB"
            else:
                return "File not found"
        except:
            return "Unknown"
    
    # Placeholder methods for other modules
    def export_all_data(self):
        """Export all data to Excel"""
        messagebox.showinfo("Export", "Export functionality to be implemented")
    
    def show_inventory(self):
        """Show inventory interface"""
        self.inventory_gui.show_inventory(self.main_content)
    
    def show_recipes(self):
        """Show recipes interface"""
        self.recipes_gui.show_recipes(self.main_content)
    
    def show_sales(self):
        """Show sales interface"""
        self.sales_gui.show_sales(self.main_content)
    
    def show_reports(self):
        """Show reports interface"""
        self.reports_gui.show_reports(self.main_content)