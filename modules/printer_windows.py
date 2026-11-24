# modules/printer_windows.py - Direct Win32 Bluetooth COM Port Spooler for Windows
import ctypes
from ctypes import wintypes
import logging

logger = logging.getLogger(__name__)

def send_tspl_to_windows_com(tspl_string, com_port="COM7"):
    """
    Streams raw TSPL label commands directly to a Windows Bluetooth Outgoing COM port
    using native Win32 CreateFileW and WriteFile (bypassing pyserial baud rate configuration).
    Returns (success: bool, message: str)
    """
    if not com_port:
        com_port = "COM7"

    # Normalize device path for Windows (e.g. \\.\COM7)
    clean_port = com_port.strip().upper()
    if not clean_port.startswith(r"\\.\\"):
        device_path = rf"\\.\{clean_port}"
    else:
        device_path = clean_port

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    # 1. Open direct handle to the virtual Bluetooth serial port
    handle = kernel32.CreateFileW(
        device_path,
        0x40000000,  # GENERIC_WRITE
        0,           # Exclusive access
        None,
        3,           # OPEN_EXISTING
        0x80,        # FILE_ATTRIBUTE_NORMAL
        None
    )

    if handle == -1:
        err_code = ctypes.get_last_error()
        error_msg = f"Windows Printer Error: Unable to open {clean_port} (Error code: {err_code}). Ensure printer is ON and paired."
        logger.error(error_msg)
        return False, error_msg

    try:
        # Encode command string to raw bytes
        data = tspl_string.encode('utf-8')
        bytes_to_write = len(data)
        bytes_written = wintypes.DWORD(0)

        # 2. Write raw TSPL stream across Bluetooth
        success = kernel32.WriteFile(
            handle,
            data,
            bytes_to_write,
            ctypes.byref(bytes_written),
            None
        )

        if not success:
            err_code = ctypes.get_last_error()
            error_msg = f"Windows Printer Error: WriteFile to {clean_port} failed (Error code: {err_code})."
            logger.error(error_msg)
            return False, error_msg

        logger.info(f"Successfully transmitted {bytes_written.value} bytes to XP-237B on {clean_port}.")
        return True, f"Printed {bytes_written.value} bytes on {clean_port}"

    except Exception as e:
        error_msg = f"Unexpected Windows Serial Exception on {clean_port}: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

    finally:
        # 3. Always release hardware handle
        kernel32.CloseHandle(handle)