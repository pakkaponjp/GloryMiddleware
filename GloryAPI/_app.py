#
# File: GloryAPI/app.py
# Author: Pakkapon Jirachatmongkon
# Date: July 22, 2025
# Description: Main Flask application for GloryAPI, integrating FCC SOAP client and event listener.
#
# License: P POWER GENERATING CO.,LTD.
# 
# Usage: Run this file to start the Flask web server and integrated services.
#
import os
from flask import Flask
from config import Config
import logging

# Import Blueprints
from routes.fcc_route import fcc_bp

# Import Event Listener and configure logging
from services.fcc_event_listener import FccEventListener

# Configure logging for the entire application
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Set other configurations if needed
    # Default limits for FCC device monitoring
    app.config.setdefault("FCC_LIMIT_DEFAULT", {
        "warn_low_pct": 0.10,  #10% of capacity
        "warn_high_pct": 0.90, #90% of capacity
    })

    # Set specific overrides for certain device models if needed
    app.config.setdefault("FCC_LIMITS_OVERRIDES", {
        # Example for specific device model overrides 
        # ("EUR", 1000, 1): {"min": 5, "max": 120, "warn_low": 10, "warn_high": 110},   
    })


    # Register blueprints
    app.register_blueprint(fcc_bp)

    # Initialize and start FCC Event Listener
    # This needs to be done only once when the app starts
    with app.app_context():
        should_start = (os.environ.get("WERKZEUG_RUN_MAIN") == "true") or not app.debug
        if not should_start:
            logger.info("Skipping event listener start in reloader process.")
            
            # The listener will forward events to GloryIntermedia's configured URL
            # You can add an optional internal callback if GloryAPI needs to react to events itself
            event_listener = FccEventListener(
                listen_ip=app.config['GLORY_API_IP_FOR_EVENTS'],
                listen_port=app.config['FCC_EVENT_LISTENER_PORT'],
                forward_url=app.config['GLORY_INTERMEDIA_EVENT_FORWARD_URL']
                # event_callback=some_internal_handler # Optional internal handler for GloryAPI
            )
            # Start listener in a separate thread
            event_listener.start()
            app.event_listener = event_listener # Store it on app for potential 
            
        else:
            logger.info("Skipping Event Listener in Flask reloader child process.")

    @app.route('/')
    def index():
        return "GloryAPI is running!"

    return app

if __name__ == '__main__':
    app = create_app()
    # For development, run with Flask's built-in server
    app.run(host='0.0.0.0', port=5000, debug=Config.DEBUG, use_reloader=False)

    # In production, you would run with Gunicorn:
    # gunicorn -w 4 -b 0.0.0.0:5000 app:create_app()