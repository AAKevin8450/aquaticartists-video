"""
Application entry point.
Run this file to start the Flask development server.
"""
from app import create_app

# Create Flask application
app = create_app()

if __name__ == '__main__':
    # Run development server
    app.run(
        host='0.0.0.0',
        port=5501,
        debug=True
    )
