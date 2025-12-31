# GloryAPI/app.py
import os
from flask import Flask
from config import Config
import logging

from routes.fcc_route import fcc_bp
from services.fcc_event_listener import FccEventListener

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.config.setdefault("FCC_LIMIT_DEFAULT", {
        "warn_low_pct": 0.10,
        "warn_high_pct": 0.90,
    })

    app.config.setdefault("FCC_LIMITS_OVERRIDES", {})

    # Register blueprints
    app.register_blueprint(fcc_bp)

    # Initialize and start FCC Event Listener (but don't let failures kill the app)
    with app.app_context():
        # If you ever use Flask debug reloader with use_reloader=True:
        is_main_process = (os.environ.get("WERKZEUG_RUN_MAIN") == "true") or not app.debug

        if is_main_process:
            try:
                event_listener = FccEventListener(
                    listen_ip=app.config['GLORY_API_IP_FOR_EVENTS'],
                    listen_port=app.config['FCC_EVENT_LISTENER_PORT'],
                    forward_url=app.config['GLORY_INTERMEDIA_EVENT_FORWARD_URL'],
                )
                event_listener.start()
                app.event_listener = event_listener
                logger.info("FCC Event Listener started.")
            except Exception:
                logger.exception("Failed to start FCC Event Listener. Continuing without it.")
        else:
            logger.info("Skipping event listener in Flask reloader child process.")

    @app.route('/')
    def index():
        return "GloryAPI is running!"

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
        use_reloader=False,  # you already have this
    )
