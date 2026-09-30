# modules/printer_android.py - RawBT Android Tablet Bluetooth Bridge Formatter
import base64
import urllib.parse

def format_rawbt_intent_url(tspl_string):
    """
    Encodes TSPL string into an Android rawbt: protocol URL.
    Can be launched from an Android Chrome browser tab to print silently over Bluetooth.
    """
    encoded_commands = urllib.parse.quote(tspl_string)
    return f"rawbt:{encoded_commands}"

def format_rawbt_websocket_payload(tspl_string):
    """
    Formats TSPL commands into a standard JSON-ready payload
    for RawBT's local Android WebSocket service running on ws://localhost:40213.
    """
    raw_bytes = tspl_string.encode('utf-8')
    base64_data = base64.b64encode(raw_bytes).decode('ascii')
    return {
        "type": "raw",
        "data": base64_data
    }