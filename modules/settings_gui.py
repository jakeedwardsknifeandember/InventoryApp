# settings_gui.py - All settings-related GUI code
import customtkinter as ctk
import pandas as pd
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
import os
import shutil

class SettingsGUI:
    def __init__(self, window, db, config):
        self.window = window
        self.db = db
        self.config = config
        self.main_content = None
        
        # Store the current appearance mode for tracking
        self.current_appearance_mode = ctk.get_appearance_mode()

        # Load saved theme on startup
        self.load_initial_theme()

    def load_initial_theme(self):
        """Load saved theme preference on startup"""
        try:
            saved_theme = self.config.get('theme', 'Dark')
            ctk.set_appearance_mode(saved_theme)
            
            # Also update the dropdown if we're in settings
            if hasattr(self, 'theme_var'):
                self.theme_var.set(saved_theme)
        except:
            pass  # Use default if can't load
    
    def clear_main_content(self):
        if self.main_content:
            for widget in self.main_content.winfo_children():
                widget.destroy()
    
    def show_settings(self, main_content_frame):
        self.main_content = main_content_frame
        self.clear_main_content()
        
        # Create tabview for settings
        settings_tabs = ctk.CTkTabview(self.main_content)
        settings_tabs.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Configure tab colors for better theme support
        settings_tabs.configure(
            segmented_button_selected_color="#2b7cff",
            segmented_button_selected_hover_color="#1e5bbf",
            text_color=("#2c2c2c", "#f0f0f0")  # Dark/Light text colors
        )
        
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
        # Title with theme-aware colors
        title_label = ctk.CTkLabel(parent_frame, text="Business Information", 
                                  font=("Arial", 22, "bold"))
        title_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        title_label.pack(pady=10)
        
        # Form frame
        form_frame = ctk.CTkFrame(parent_frame)
        form_frame.pack(pady=20, padx=50, fill="x")
        
        # Current business info
        current_info = f"Current Business: {self.config['business_name']}"
        info_label = ctk.CTkLabel(form_frame, text=current_info, 
                                 font=("Arial", 14, "bold"))
        info_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        info_label.pack(pady=10)
        
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
            
            label = ctk.CTkLabel(row_frame, text=label_text, 
                                width=150, anchor="w")
            label.configure(text_color=("#2c2c2c", "#f0f0f0"))
            label.pack(side="left", padx=10)
            
            entry = ctk.CTkEntry(row_frame, width=250)
            entry.insert(0, default_value)
            entry.pack(side="left", padx=10)
            
            self.settings_entries[field_name] = entry
        
        # Tax rate setting
        tax_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        tax_frame.pack(fill="x", pady=10)
        
        tax_label = ctk.CTkLabel(tax_frame, text="Tax Rate (%):", 
                                width=150, anchor="w")
        tax_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        tax_label.pack(side="left", padx=10)
        
        self.tax_rate_var = tk.StringVar(value="12.0")  # Default 12%
        tax_entry = ctk.CTkEntry(tax_frame, textvariable=self.tax_rate_var, width=250)
        tax_entry.pack(side="left", padx=10)
        
        # Business address
        address_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        address_frame.pack(fill="x", pady=10)
        
        address_label = ctk.CTkLabel(address_frame, text="Business Address:", 
                                    width=150, anchor="w")
        address_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        address_label.pack(side="left", padx=10)
        
        self.address_text = ctk.CTkTextbox(address_frame, width=250, height=80)
        self.address_text.pack(side="left", padx=10)
        self.address_text.insert("1.0", "123 Business Street\nCity, Country")  # Default
        
        # Save button
        button_frame = ctk.CTkFrame(parent_frame)
        button_frame.pack(pady=20)
        
        save_btn = ctk.CTkButton(button_frame, text="💾 Save Settings",
                                command=self.save_business_settings,
                                fg_color="#27ae60", hover_color="#219653",
                                width=150, height=40)
        save_btn.pack(side="left", padx=10)
        
        reset_btn = ctk.CTkButton(button_frame, text="Reset to Defaults",
                                 command=self.reset_settings,
                                 width=150, height=40)
        reset_btn.pack(side="left", padx=10)
        
        # Status label
        self.settings_status_label = ctk.CTkLabel(parent_frame, text="", 
                                                 font=("Arial", 12))
        self.settings_status_label.pack(pady=10)
    
    def save_business_settings(self):
        """Save business settings PERMANENTLY"""
        try:
            # Collect settings
            new_settings = {}
            
            for field_name, entry in self.settings_entries.items():
                value = entry.get()
                
                if field_name == 'low_stock_warning':
                    try:
                        new_settings[field_name] = int(value)
                    except ValueError:
                        self.settings_status_label.configure(
                            text="Low Stock must be a number",
                            text_color="red"
                        )
                        return
                else:
                    new_settings[field_name] = value
            
            # Get tax rate
            try:
                tax_rate = float(self.tax_rate_var.get())
                new_settings['tax_rate'] = tax_rate
            except ValueError:
                self.settings_status_label.configure(
                    text="Tax Rate must be a number",
                    text_color="red"
                )
                return
            
            # Get address
            address = self.address_text.get("1.0", "end-1c").strip()
            new_settings['business_address'] = address
            
            # Validate
            if not new_settings.get('business_name'):
                self.settings_status_label.configure(
                    text="Business Name is required",
                    text_color="red"
                )
                return
            
            # FIXED: Save using the Config object in db
            if hasattr(self.db, 'config'):
                success = self.db.config.update(new_settings)
                
                if success:
                    # Update window title
                    self.window.title(f"Inventory Manager - {new_settings['business_name']}")
                    
                    # Update current config dictionary
                    for key, value in new_settings.items():
                        self.config[key] = value
                    
                    self.settings_status_label.configure(
                        text="✅ Settings saved permanently!",
                        text_color="green"
                    )
                else:
                    self.settings_status_label.configure(
                        text="❌ Error saving to config file",
                        text_color="red"
                    )
            else:
                # Fallback: Update in memory only
                self.config.update(new_settings)
                self.window.title(f"Inventory Manager - {new_settings['business_name']}")
                self.settings_status_label.configure(
                    text="✅ Settings saved (session only)",
                    text_color="orange"
                )
            
        except Exception as e:
            self.settings_status_label.configure(
                text=f"❌ Error: {str(e)}",
                text_color="red"
            )

    def refresh_business_display(self):
        """Refresh business name display in the app"""
        # This method can be called to update any business name displays
        # For now, we'll just update the window title which is already done
        pass
    
    def reset_settings(self):
        """Reset settings to defaults PERMANENTLY"""
        confirm = messagebox.askyesno("Reset Settings", 
                                     "Reset all settings to defaults?\n\n"
                                     "This will also save changes to file.")
        if confirm:
            # Reset config to defaults
            success = self.db.config.reset_to_defaults()
            
            if success:
                # Update form fields
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
                
                # Update window title
                self.window.title(f"Inventory Manager - My Bakery Shop")
                
                self.settings_status_label.configure(
                    text="✅ Settings reset to defaults and saved!",
                    text_color="green"
                )
            else:
                self.settings_status_label.configure(
                    text="❌ Error resetting settings",
                    text_color="red"
                )
    
    def show_preferences_settings(self, parent_frame):
        """Show application preferences"""
        # Title with theme-aware colors
        title_label = ctk.CTkLabel(parent_frame, text="Application Preferences", 
                                  font=("Arial", 22, "bold"))
        title_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        title_label.pack(pady=10)
        
        # Theme selection
        theme_frame = ctk.CTkFrame(parent_frame)
        theme_frame.pack(pady=20, padx=50, fill="x")
        
        theme_label = ctk.CTkLabel(theme_frame, text="Theme:", 
                                  font=("Arial", 14))
        theme_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        theme_label.pack(pady=10)
        
        # Get current theme
        current_theme = ctk.get_appearance_mode()
        self.theme_var = tk.StringVar(value=current_theme)
        
        theme_menu = ctk.CTkOptionMenu(theme_frame,
                                      values=["System", "Light", "Dark"],
                                      variable=self.theme_var,
                                      width=200)
        theme_menu.pack(pady=10)
        
        # Apply theme button
        apply_btn = ctk.CTkButton(theme_frame, text="Apply Theme",
                                 command=self.apply_theme,
                                 width=150)
        apply_btn.pack(pady=10)
        
        # Default units
        units_frame = ctk.CTkFrame(parent_frame)
        units_frame.pack(pady=20, padx=50, fill="x")
        
        units_title = ctk.CTkLabel(units_frame, text="Default Units:", 
                                  font=("Arial", 14))
        units_title.configure(text_color=("#2c2c2c", "#f0f0f0"))
        units_title.pack(pady=10)
        
        # Weight units
        weight_frame = ctk.CTkFrame(units_frame, fg_color="transparent")
        weight_frame.pack(fill="x", pady=5)
        
        weight_label = ctk.CTkLabel(weight_frame, text="Weight:", width=80)
        weight_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        weight_label.pack(side="left", padx=10)
        
        self.weight_unit_var = tk.StringVar(value="g")
        weight_menu = ctk.CTkOptionMenu(weight_frame,
                                       values=["g", "kg", "mg"],
                                       variable=self.weight_unit_var,
                                       width=100)
        weight_menu.pack(side="left", padx=10)
        
        # Volume units
        volume_frame = ctk.CTkFrame(units_frame, fg_color="transparent")
        volume_frame.pack(fill="x", pady=5)
        
        volume_label = ctk.CTkLabel(volume_frame, text="Volume:", width=80)
        volume_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        volume_label.pack(side="left", padx=10)
        
        self.volume_unit_var = tk.StringVar(value="ml")
        volume_menu = ctk.CTkOptionMenu(volume_frame,
                                       values=["ml", "L"],
                                       variable=self.volume_unit_var,
                                       width=100)
        volume_menu.pack(side="left", padx=10)
        
        # Save preferences
        save_prefs_btn = ctk.CTkButton(parent_frame, text="💾 Save Preferences",
                                      command=self.save_preferences,
                                      fg_color="#27ae60", hover_color="#219653",
                                      width=200, height=40)
        save_prefs_btn.pack(pady=20)
    
    def apply_theme(self):
        """Apply selected theme"""
        theme = self.theme_var.get()
        
        # Set the global appearance mode
        ctk.set_appearance_mode(theme)
        
        # Update main application theme
        self.update_main_app_theme()
        
        # Save theme preference
        self.save_theme_preference(theme)
        
        # Force settings window to reload
        if self.main_content:
            self.show_settings(self.main_content)
        
        # Show confirmation
        message = f"Theme changed to {theme} mode."
        if theme == "System":
            message = "Theme set to follow your operating system."
        
        messagebox.showinfo("Theme Applied", message)
    
    def update_main_app_theme(self):
        """Update the main application's theme"""
        try:
            # Get main app reference from window
            if hasattr(self.window, 'main_app'):
                main_app = self.window.main_app
                if hasattr(main_app, 'update_theme_colors'):
                    main_app.update_theme_colors()
        except Exception as e:
            print(f"Error updating main app theme: {e}")
            # Fallback: try to find and update sidebar directly
            self.fallback_sidebar_update()
    
    def fallback_sidebar_update(self):
        """Fallback method to update sidebar if main app reference not found"""
        try:
            # Look for sidebar frame in window children
            for widget in self.window.winfo_children():
                if isinstance(widget, ctk.CTkFrame) and widget.winfo_width() < 250:
                    # Likely the sidebar (narrow frame on left)
                    current_theme = ctk.get_appearance_mode()
                    
                    if current_theme == "Dark":
                        widget.configure(fg_color="#2b2b2b")
                        for child in widget.winfo_children():
                            if isinstance(child, ctk.CTkLabel):
                                child.configure(text_color="#f0f0f0")
                            elif isinstance(child, ctk.CTkButton):
                                child.configure(text_color="#f0f0f0")
                    else:
                        widget.configure(fg_color="#f5f5f5")
                        for child in widget.winfo_children():
                            if isinstance(child, ctk.CTkLabel):
                                child.configure(text_color="#2c2c2c")
                            elif isinstance(child, ctk.CTkButton):
                                child.configure(text_color="#2c2c2c")
        except:
            pass
    
    def save_theme_preference(self, theme):
        """Save theme preference to config"""
        try:
            # Update in memory config
            self.config['theme'] = theme
            
            # Save to file if possible
            if hasattr(self.db, 'config'):
                self.db.config.update({'theme': theme})
        except:
            pass  # Silently fail if can't save
    
    def save_preferences(self):
        """Save application preferences"""
        # Save theme if changed
        current_theme = ctk.get_appearance_mode()
        if self.theme_var.get() != current_theme:
            self.apply_theme()
        
        # Save other preferences
        messagebox.showinfo("Preferences", 
                          "Preferences saved!\n\n"
                          f"Theme: {self.theme_var.get()}\n"
                          f"Default Weight Unit: {self.weight_unit_var.get()}\n"
                          f"Default Volume Unit: {self.volume_unit_var.get()}")
        
        # Save to config
        if hasattr(self.db, 'config'):
            self.db.config.update({
                'default_weight_unit': self.weight_unit_var.get(),
                'default_volume_unit': self.volume_unit_var.get()
            })
    
    def show_data_management(self, parent_frame):
        """Show data management options"""
        # Title with theme-aware colors
        title_label = ctk.CTkLabel(parent_frame, text="Data Management", 
                                  font=("Arial", 22, "bold"))
        title_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        title_label.pack(pady=10)
        
        # Warning frame
        warning_frame = ctk.CTkFrame(parent_frame, border_width=2, 
                                    border_color="#e74c3c", corner_radius=10)
        warning_frame.pack(pady=20, padx=50, fill="x")
        
        warning_title = ctk.CTkLabel(warning_frame, text="⚠️ IMPORTANT WARNING", 
                                    font=("Arial", 16, "bold"),
                                    text_color="#e74c3c")
        warning_title.pack(pady=10)
        
        warning_text = "• ALWAYS close Excel before these operations\n"
        warning_text += "• Make sure you have backups\n"
        warning_text += "• Some actions cannot be undone!"
        
        warning_content = ctk.CTkLabel(warning_frame, text=warning_text,
                                      text_color="#e74c3c")
        warning_content.pack(pady=10)
        
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

    def darken_color(self, hex_color):
        """Darken a hex color for hover effect"""
        # Remove # if present
        hex_color = hex_color.lstrip('#')
        
        # Convert to RGB
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        
        # Darken by 20%
        darkened = tuple(max(0, int(c * 0.8)) for c in rgb)
        
        # Convert back to hex
        return f"#{darkened[0]:02x}{darkened[1]:02x}{darkened[2]:02x}"

    def export_all_data(self):
        """Export all data to a single Excel file"""
        try:
            # Get all data
            tabs = {
                'Products': self.db.read_tab('Products'),
                'Ingredients': self.db.read_tab('Ingredients'),
                'Recipes': self.db.read_tab('Recipes'),
                'Sales': self.db.read_tab('Sales'),
                'Inventory_Logs': self.db.read_tab('Inventory_Log')
            }
            
            # Check if we have any data
            empty_count = sum(1 for df in tabs.values() if df.empty)
            if empty_count == len(tabs):
                messagebox.showwarning("No Data", "No data available to export.")
                return
            
            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"inventory_backup_{timestamp}.xlsx"
            
            # Export to Excel
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                for sheet_name, df in tabs.items():
                    if not df.empty:
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            # Add summary sheet
            with pd.ExcelWriter(filename, engine='openpyxl', mode='a') as writer:
                summary_data = {
                    'Sheet': [],
                    'Rows': [],
                    'Columns': [],
                    'Export Date': []
                }
                
                for sheet_name, df in tabs.items():
                    if not df.empty:
                        summary_data['Sheet'].append(sheet_name)
                        summary_data['Rows'].append(len(df))
                        summary_data['Columns'].append(len(df.columns))
                        summary_data['Export Date'].append(datetime.now().strftime("%Y-%m-%d %H:%M"))
                
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            messagebox.showinfo("Export Successful", 
                              f"All data exported to:\n{filename}\n\n"
                              f"Contains {len([df for df in tabs.values() if not df.empty])} sheets.")
            
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export: {str(e)}")

    def export_products_data(self):
        """Export products data to Excel"""
        self.export_single_tab('Products', 'products')
    
    def export_ingredients_data(self):
        """Export ingredients data to Excel"""
        self.export_single_tab('Ingredients', 'ingredients')
    
    def export_recipes_data(self):
        """Export recipes data to Excel"""
        self.export_single_tab('Recipes', 'recipes')
    
    def export_sales_data(self):
        """Export sales data to Excel"""
        self.export_single_tab('Sales', 'sales')
    
    def export_inventory_logs(self):
        """Export inventory logs to Excel"""
        self.export_single_tab('Inventory_Log', 'inventory_logs')
    
    def export_single_tab(self, tab_name, file_prefix):
        """Export a single tab to Excel"""
        try:
            df = self.db.read_tab(tab_name)
            
            if df.empty:
                messagebox.showwarning("No Data", f"No {file_prefix} data available to export.")
                return
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{file_prefix}_{timestamp}.xlsx"
            
            df.to_excel(filename, index=False)
            
            messagebox.showinfo("Export Successful", 
                              f"{tab_name} data exported to:\n{filename}\n"
                              f"Rows: {len(df)}, Columns: {len(df.columns)}")
            
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export {tab_name}: {str(e)}")

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
            
            progress_label = ctk.CTkLabel(progress_window, text="🗑️ Clearing all data...", 
                                        font=("Arial", 16, "bold"))
            progress_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
            progress_label.pack(pady=20)
            
            progress_label2 = ctk.CTkLabel(progress_window, text="Starting...")
            progress_label2.configure(text_color=("#2c2c2c", "#f0f0f0"))
            progress_label2.pack(pady=10)
            
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
                progress_label2.configure(text=f"Clearing {tab_name}... ({i}/5)")
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
                label = ctk.CTkLabel(self.main_content, text="✅ Database cleared successfully!", 
                                   font=("Arial", 16, "bold"))
                label.configure(text_color=("#2c2c2c", "#f0f0f0"))
                label.pack(pady=50)
            
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
        # Title with theme-aware colors
        title_label = ctk.CTkLabel(parent_frame, text="About Inventory Manager", 
                                  font=("Arial", 22, "bold"))
        title_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        title_label.pack(pady=10)
        
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
        
        about_label = ctk.CTkLabel(info_frame, text=about_text,
                                  font=("Arial", 11),
                                  justify="left")
        about_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        about_label.pack(pady=20, padx=20)
        
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
        
        sys_label = ctk.CTkLabel(sys_frame, text=sys_info,
                                font=("Arial", 10),
                                justify="left")
        sys_label.configure(text_color=("#2c2c2c", "#f0f0f0"))
        sys_label.pack(pady=10, padx=10)
    
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