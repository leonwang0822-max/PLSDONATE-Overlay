import asyncio
import json
import logging
from datetime import datetime

from quart import Quart, render_template, websocket, request, jsonify
import websockets

app = Quart(__name__)

# Configuration
config_file = "config.json"
config = {
    "user_id": None,
    "min_amount": 0
}

# Load config
try:
    with open(config_file, "r") as f:
        saved_config = json.load(f)
        config.update(saved_config)
except FileNotFoundError:
    pass

# State
connected_clients = set()
BASE_WS = "wss://stream.plsdonate.com/api/user/{}/websocket"
donation_history = []  # Store session history

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def save_config():
    with open(config_file, "w") as f:
        json.dump(config, f)

async def broadcast(message):
    for client in connected_clients:
        try:
            await client.send(json.dumps(message))
        except Exception:
            pass

async def plsdonate_listener():
    current_user_id = None
    
    while True:
        target_user_id = config.get("user_id")
        
        if not target_user_id:
            await asyncio.sleep(1)
            continue
            
        url = BASE_WS.format(target_user_id)
        logger.info(f"Connecting to {url}...")
        
        try:
            async with websockets.connect(url) as ws:
                logger.info(f"Connected to stream for user {target_user_id}")
                current_user_id = target_user_id
                
                async for msg in ws:
                    # If user ID changed, break to reconnect
                    if config.get("user_id") != current_user_id:
                        logger.info("User ID changed, reconnecting...")
                        break
                        
                    try:
                        data = json.loads(msg)
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Process donation
                        if "sender" in data and "amount" in data:
                            sender_name = data["sender"].get("displayName", "Unknown")
                            sender_user = data["sender"].get("username", "Unknown")
                            amount = data.get("amount", 0)
                            message = data.get("message", "")
                            
                            event = {
                                "type": "donation",
                                "timestamp": timestamp,
                                "sender_name": sender_name,
                                "sender_user": sender_user,
                                "amount": amount,
                                "message": message,
                                "raw": data
                            }
                            
                            # Add to history
                            donation_history.append(event)
                            # Keep history reasonable
                            if len(donation_history) > 100:
                                donation_history.pop(0)
                                
                            logger.info(f"Donation: {sender_name} - {amount}")
                            await broadcast(event)
                        else:
                            # Forward other events if needed
                            pass
                            
                    except json.JSONDecodeError:
                        logger.error(f"Received non-JSON message: {msg}")
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        
        except Exception as e:
            logger.error(f"Connection error: {e}")
            await asyncio.sleep(5) # Wait before retry

@app.before_serving
async def startup():
    app.add_background_task(plsdonate_listener)

@app.route("/")
async def index():
    return await render_template("index.html", config=config)

@app.route("/leaderboard")
async def leaderboard():
    return await render_template("leaderboard.html")

@app.route("/api/settings", methods=["POST"])
async def update_settings():
    data = await request.get_json()
    if "user_id" in data:
        config["user_id"] = data["user_id"]
    if "min_amount" in data:
        config["min_amount"] = int(data["min_amount"])
    
    save_config() # Save to file
    
    return jsonify({"status": "ok", "config": config})

@app.route("/api/history")
async def get_history():
    return jsonify(donation_history)

@app.websocket("/ws")
async def ws():
    connected_clients.add(websocket._get_current_object())
    try:
        while True:
            await websocket.receive() # Keep connection open
    except asyncio.CancelledError:
        connected_clients.remove(websocket._get_current_object())
    except Exception:
        connected_clients.remove(websocket._get_current_object())

if __name__ == "__main__":
    import hypercorn.asyncio
    from hypercorn.config import Config
    
    config_h = Config()
    config_h.bind = ["localhost:5000"]
    asyncio.run(hypercorn.asyncio.serve(app, config_h))
