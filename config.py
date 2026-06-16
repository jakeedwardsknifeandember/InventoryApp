# config.py - Configuration Manager for Inventory App
import json
import os

class Config:
    def __init__(self, config_file='config.json'):
        """Initialize configuration manager"""
        self.config_file = config_file
        self.default_config = {
            'business_name': "My Bakery Shop",
            'currency': "₱",
            'date_format': "%Y-%m-%d",
            'low_stock_warning': 20,
            'excel_file': 'data/inventory.db',  # 🌟 FIXED: Changed .xlsx to .db
            'tax_rate': 12.0,
            'business_address': "123 Business Street\nCity, Country"
        }
        self.config = self._load_config()
    
    def _load_config(self):
        """Load configuration from file or return defaults"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return self.default_config.copy()
        return self.default_config.copy()
    
    def save(self):
        """Save current configuration to file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"⚠️ Config save error: {e}")
            return False
    
    def update(self, new_settings):
        """Update configuration with new settings"""
        for key, value in new_settings.items():
            # Special handling for numeric fields
            if key == 'low_stock_warning':
                try:
                    self.config[key] = int(value)
                except ValueError:
                    self.config[key] = self.default_config[key]
            elif key == 'tax_rate':
                try:
                    self.config[key] = float(value)
                except ValueError:
                    self.config[key] = self.default_config[key]
            else:
                self.config[key] = value
        
        return self.save()
    
    def get(self, key, default=None):
        """Get a configuration value"""
        return self.config.get(key, default)
    
    def reset(self):
        """Reset all settings to defaults"""
        self.config = self.default_config.copy()
        return self.save()
    
    # Dictionary-style access
    def __getitem__(self, key):
        return self.config[key]
    
    def __setitem__(self, key, value):
        self.config[key] = value
        self.save()
    
    def __contains__(self, key):
        return key in self.config
    
    # Property for backward compatibility
    @property
    def CLIENT_CONFIG(self):
        """Backward compatibility property - returns config dict"""
        return self.config

# Create global instances for different access styles
config = Config()  
CLIENT_CONFIG = config.config