#
# File: GloryAPI/services/fcc_even_listener.py
# Author: Pakkapon Jirachatmongkon
# Date: July 22, 2025
# Description:
#
# License: P POWER GENERATING CO.,LTD.
# 
# Usage:
#
import socket
import threading
import xml.etree.ElementTree as ET
import requests # For forwarding event to GloryIntermedia
import logging

logger = logging.getLogger(__name__)

class FccEventListener:
    def __init__(self, listen_ip, listen_port, forward_url, event_callback=None):
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.forward_url = forward_url
        self.event_callback = event_callback # Optional: for internal processing before forwarding
        self.server_socket = None
        self.running = False
        self.listen_thread = None

    def start(self):
        if self.running:
            logger.info("FCC Event Listener is already running.")
            return
        
        self.running = True
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.listen_ip, self.listen_port))
            self.server_socket.listen(1) # Only expecting one connection from FCC
            logger.info(f"Listening for FCC events on {self.listen_ip}:{self.listen_port}")

            self.listen_thread = threading.Thread(target=self._accept_connections, daemon=True)
            self.listen_thread.start()
        except Exception as e:
            logger.error(f"Failed to start Even Listener: {e}")
            self.running = False # Mark as not running if startup fails

    def _accept_connections(self):
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                logger.info(f"Accepted FCC event connection from {addr}")
                # Handle each connection in a new thread if multiple connections are possible,
                # but for FCC events, typically only one persistent connection.
                self._handle_client(conn) 
            except socket.timeout:
                continue # No connection within timeout, continue loop
            except Exception as e:
                if self.running: # Only log if not intentionally stopped
                    logger.error(f"Error accepting FCC event connection: {e}")
                break # Break loop if a serious error occurs

    def _handle_client(self, conn):
        buffer = ""
        try:
            while self.running:
                data = conn.recv(4096).decode('utf-8', errors='ignore') # Use ignore for robustness
                if not data:
                    logger.info("FCC event client disconnected.")
                    break # Client disconnected

                buffer += data
                # Simple check for a complete XML message (adjust based on actual event XML structure)
                # FCC documentation should specify event message structure (e.g., ends with specific tag)
                # A more robust parser would be an XML stream parser or look for common root tags.
                if "</notification>" in buffer or "</Event>" in buffer: # Adjust based on FCC event XML root tag
                    try:
                        # Attempt to parse what's in the buffer as XML
                        root = ET.fromstring(buffer)
                        xml_string = ET.tostring(root, encoding='unicode') # Convert back to string for forwarding

                        logger.debug(f"Received FCC Event XML: {xml_string}")

                        # Call internal callback if provided
                        if self.event_callback:
                            self.event_callback(root)

                        # Forward the event to GloryIntermedia
                        self._forward_event(xml_string)

                        buffer = "" # Reset buffer after successful processing
                    except ET.ParseError as pe:
                        # This might mean the message is incomplete or malformed.
                        # For production, you might want more sophisticated buffering/parsing.
                        logger.warning(f"Partial or malformed XML received from FCC: {buffer[:200]}... Error: {pe}")
                        # Keep the buffer for next recv, or clear if you think it's junk
                        # For now, let's assume it's incomplete and wait for more data.
                    except Exception as fe:
                        logger.error(f"Error processing or forwarding FCC event: {fe}")
                        # If a forwarding error occurs, you might want to log it and attempt to re-forward or queue.
                        buffer = "" # Clear buffer to avoid processing same error repeatedly

        except Exception as e:
            logger.error(f"Error in FCC event client handler: {e}")
        finally:
            if conn:
                conn.close()
            logger.info("FCC event client handler stopped.")
            # If the connection drops, and FCC needs a persistent connection, you might want to attempt to restart listening.
            # However, for simplicity, we'll let accept_connections loop restart if it's designed for multiple incoming.

    def _forward_event(self, event_xml_string):
        """Forwards the raw XML event string to GloryIntermedia."""
        try:
            headers = {'Content-Type': 'application/xml'} # FCC events are typically XML
            response = requests.post(self.forward_url, data=event_xml_string, headers=headers, timeout=5)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            logger.info(f"Successfully forwarded FCC event to {self.forward_url} (Status: {response.status_code})")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to forward FCC event to {self.forward_url}: {e}")
            # Implement retry logic or a message queue here for production reliability

    def stop(self):
        self.running = False
        if self.server_socket:
            logger.info("Closing FCC Event Listener socket...")
            self.server_socket.close() # This will cause _accept_connections to break from accept()
        if self.listen_thread and self.listen_thread.is_alive():
            self.listen_thread.join(timeout=2) # Give thread time to shut down
        logger.info("FCC Event Listener stopped.")

if __name__ == '__main__':
    # This block is for testing this module independently
    from config import Config
    import time

    logging.basicConfig(level=logging.INFO) # Swt to DEBUG for more verbosity

    # Dummy callbac for testing
    def test_event_callback(xml_data):
        print(f"\n[TEST] Recieved and parsed event internally: {ET.tostring(xml_data, encoding='unicode')}")

        print("Testing FccEventListener...")     
        # NOTE: In a real test, you'd need FCC to send an even, or simulate it.
        # For this test, just showing it starts lintening.
        listener = FccEventListener(
            listen_ip=Config.GLORY_API_IP_FOR_EVENTS,
            listen_port=Config.FCC_EVENT_LISTENER_PORT,
            forward_url="http://localhost:9999/dummy-event-receiver", # Use a dummy URL for testing
            event_callback=test_event_callback
        )

        try:
            listener.start()
            print(f"Listener started on {Config.GLORY_API_IP_FOR_EVENTS}:{Config.FCC_EVEN_LISTENER_PORT}")
            print("Waiting for 60 seconds (or press Ctrl+C to stop)...")
            time.sleep(60) # Keep the listener running for a while
        except KeyboardInterrupt:
            print("\nStopping litener due to keyboard interrupt.")
        finally:
            listener.stop()
            print("Listener stopped.")