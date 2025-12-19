"""
Flask application factory.
"""
from flask import Flask
import logging
from pathlib import Path


def create_app(config_name=None):
    """
    Create and configure Flask application.

    Args:
        config_name: Configuration name ('development', 'production', 'testing')

    Returns:
        Configured Flask application
    """
    app = Flask(__name__)

    # Load configuration
    from app.config import get_config
    config_class = get_config(config_name)
    app.config.from_object(config_class)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO if not app.config['DEBUG'] else logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize database
    try:
        from app.database import init_db
        init_db(app)
        app.logger.info("Database initialized successfully")
    except Exception as e:
        app.logger.error(f"Database initialization failed: {e}")
        raise

    # Validate AWS configuration (warn if missing, don't fail)
    try:
        from app.config import Config
        Config.validate_aws_config()
        app.logger.info("AWS configuration validated")
    except ValueError as e:
        app.logger.warning(f"AWS configuration warning: {e}")
        app.logger.warning("Some features may not work without proper AWS configuration")

    # Register blueprints
    from app.routes import (
        main, upload, video_analysis, image_analysis, collections,
        history, analysis, transcription, dashboard, nova_analysis
    )

    app.register_blueprint(main.bp)
    app.register_blueprint(upload.bp)
    app.register_blueprint(video_analysis.bp)
    app.register_blueprint(image_analysis.bp)
    app.register_blueprint(collections.bp)
    app.register_blueprint(history.bp)
    app.register_blueprint(analysis.bp)
    app.register_blueprint(transcription.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(nova_analysis.bp)

    app.logger.info("All blueprints registered (including Nova)")

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return {'error': 'Not found'}, 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"Internal error: {error}")
        return {'error': 'Internal server error'}, 500

    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {
            'status': 'healthy',
            'app': 'AWS Video & Image Analysis',
            'version': '1.0.0'
        }, 200

    # Template context processors
    @app.context_processor
    def utility_processor():
        """Make utility functions available in templates."""
        from app.utils.formatters import (
            format_file_size, format_timestamp, format_confidence,
            format_job_status, format_analysis_type
        )
        return {
            'format_file_size': format_file_size,
            'format_timestamp': format_timestamp,
            'format_confidence': format_confidence,
            'format_job_status': format_job_status,
            'format_analysis_type': format_analysis_type
        }

    app.logger.info(f"Flask app created successfully in {app.config.get('FLASK_ENV', 'development')} mode")

    return app
