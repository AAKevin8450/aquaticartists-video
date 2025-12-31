"""
Directory browsing endpoints.

Routes:
- POST /api/files/browse - Browse directory structure for folder picker
- POST /api/files/system-browse - Open native OS folder browser dialog
"""
from flask import Blueprint, request, jsonify, current_app
import os

bp = Blueprint('directory_browser', __name__)


@bp.route('/api/files/browse', methods=['POST'])
def browse_directory():
    """
    Browse directory structure for folder picker.

    Expected JSON:
        {
            "path": "E:\\"  # optional, defaults to drives on Windows or / on Linux
        }
    """
    try:
        data = request.get_json() or {}
        requested_path = data.get('path', '')

        import platform
        is_windows = platform.system() == 'Windows'

        # Get available drives on Windows
        drives = []
        if is_windows:
            import string
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)

        # Determine current path
        if not requested_path:
            if is_windows:
                current_path = drives[0] if drives else "C:\\"
            else:
                current_path = "/"
        else:
            current_path = os.path.abspath(requested_path)

        if not os.path.isdir(current_path):
            return jsonify({'error': f'Directory not found: {current_path}'}), 404

        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            parent_path = None

        directories = []
        try:
            for entry in os.scandir(current_path):
                if entry.is_dir():
                    try:
                        os.listdir(entry.path)
                        directories.append({
                            'name': entry.name,
                            'path': entry.path
                        })
                    except PermissionError:
                        pass
        except PermissionError:
            return jsonify({'error': f'Permission denied: {current_path}'}), 403

        directories.sort(key=lambda d: d['name'].lower())

        return jsonify({
            'current_path': current_path,
            'parent_path': parent_path,
            'directories': directories,
            'drives': drives if is_windows else []
        }), 200

    except Exception as e:
        current_app.logger.error(f"Browse directory error: {e}")
        return jsonify({'error': 'Failed to browse directory'}), 500


@bp.route('/api/files/system-browse', methods=['POST'])
def system_browse_directory():
    """
    Open native OS folder browser dialog using tkinter.

    Returns the selected folder path or empty string if cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        # Create root window and hide it
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)  # Bring dialog to front

        # Open native folder browser
        folder_path = filedialog.askdirectory(
            title="Select folder to rescan",
            mustexist=True
        )

        # Destroy the root window
        root.destroy()

        # Return the selected path (empty string if cancelled)
        return jsonify({
            'path': folder_path,
            'cancelled': not bool(folder_path)
        }), 200

    except ImportError:
        return jsonify({
            'error': 'tkinter not available - please install python-tk package'
        }), 500
    except Exception as e:
        current_app.logger.error(f"System browse error: {e}")
        return jsonify({'error': f'Failed to open folder browser: {str(e)}'}), 500
