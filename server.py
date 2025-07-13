import os
import time
import requests
from flask import Flask, request, jsonify
from PIL import Image
import io
import logging
import numpy as np
from functools import lru_cache
import traceback
import hashlib
import json
import re

app = Flask(__name__)

# =====================
# ADVANCED LOGGING SYSTEM
# =====================
class EnhancedLogger:
    def __init__(self):
        self.logger = logging.getLogger('sleeve-detector')
        self.logger.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler()
        console_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)

    def log_request(self, request):
        request_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
        self.logger.info(f"📥 REQUEST [{request_id}] FROM {request.remote_addr}")
        self.logger.debug(f"Request ID: {request_id}")
        self.logger.debug(f"User Agent: {request.headers.get('User-Agent')}")
        self.logger.debug(f"Endpoint: {request.path}")
        self.logger.debug(f"Params: {dict(request.args)}")
        return request_id

    def log_processing_start(self, request_id, texture_id):
        self.logger.info(f"🔍 PROCESSING [{request_id}] Texture: {texture_id}")

    def log_detection_step(self, request_id, step, details):
        self.logger.debug(f"⚙️ [{request_id}] {step}: {details}")

    def log_detection_result(self, request_id, color, processing_time):
        self.logger.info(f"✅ DETECTION [{request_id}] Result: RGB{tuple(color)} | Time: {processing_time:.3f}s")

    def log_error(self, request_id, error, trace=None):
        self.logger.error(f"❌ ERROR [{request_id}] {error}")
        if trace:
            self.logger.debug(f"Stack Trace [{request_id}]:\n{trace}")

    def log_response(self, request_id, response):
        self.logger.info(f"📤 RESPONSE [{request_id}]")
        self.logger.debug(f"Response Data [{request_id}]: {json.dumps(response, indent=2)}")

logger = EnhancedLogger()

# =====================
# SHIRT OVERRIDE DATABASE
# =====================
SHIRT_OVERRIDES = {
    # "123456789": [255, 0, 0],
}

# =====================
# DETECTION LOGIC
# =====================
@lru_cache(maxsize=100)
def detect_sleeve_color(texture_id):
    try:
        if texture_id in SHIRT_OVERRIDES:
            logger.log_detection_step(texture_id, "Using manual override",
                                     f"Color: {SHIRT_OVERRIDES[texture_id]}")
            return SHIRT_OVERRIDES[texture_id]

        start_time = time.time()
        logger.log_detection_step(texture_id, "Fetching texture", f"ID: {texture_id}")

        url = f"https://assetdelivery.roblox.com/v1/asset/?id={texture_id}"
        headers = {
            "User-Agent": "Roblox Sleeve Detector/2.0",
            "Accept": "image/*"
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        fetch_time = time.time() - start_time
        logger.log_detection_step(texture_id, "Texture fetched",
                                 f"Size: {len(response.content)/1024:.1f}KB | Time: {fetch_time:.3f}s")

        with Image.open(io.BytesIO(response.content)) as img:
            img = img.convert("RGBA")
            width, height = img.size

            detection_areas = [
                (int(width * 0.7), int(height * 0.4), int(width * 0.9), int(height * 0.6)),
                (int(width * 0.1), int(height * 0.4), int(width * 0.3), int(height * 0.6)),
                (int(width * 0.1), int(height * 0.3), int(width * 0.9), int(height * 0.7)),
                (int(width * 0.6), int(height * 0.2), int(width * 0.8), int(height * 0.4))
            ]

            all_opaque_pixels = []

            for i, area in enumerate(detection_areas):
                area_label = ["Right Sleeve", "Left Sleeve", "Full Arm", "Shoulder"][i]
                logger.log_detection_step(texture_id, f"Scanning {area_label}", f"Area: {area}")

                region = img.crop(area)
                pixels = np.array(region)

                opaque_mask = pixels[:, :, 3] > 128
                region_opaque_pixels = pixels[opaque_mask]

                if len(region_opaque_pixels) > 0:
                    logger.log_detection_step(texture_id, "Found opaque pixels",
                                            f"Count: {len(region_opaque_pixels)}")
                    all_opaque_pixels.extend(region_opaque_pixels)

            if len(all_opaque_pixels) == 0:
                logger.log_detection_step(texture_id, "Warning", "No opaque pixels found")
                full_pixels = np.array(img)
                opaque_mask = full_pixels[:, :, 3] > 128
                all_opaque_pixels = full_pixels[opaque_mask]

                if len(all_opaque_pixels) == 0:
                    logger.log_detection_step(texture_id, "Critical", "No opaque pixels in image")
                    return [255, 255, 255]

            avg_color = np.mean([p[:3] for p in all_opaque_pixels], axis=0).astype(int)
            detect_time = time.time() - start_time

            logger.log_detection_result(texture_id, avg_color, detect_time)
            return avg_color.tolist()

    except Exception as e:
        tb = traceback.format_exc()
        logger.log_error(texture_id, f"Detection failed: {str(e)}", tb)
        return [255, 255, 255]

# =====================
# API ENDPOINTS
# =====================
@app.route('/analyze')
def analyze_shirt():
    request_id = logger.log_request(request)
    start_time = time.time()

    texture_id = request.args.get('texture_id', '')

    if not re.match(r"^\d+$", texture_id):
        logger.log_error(request_id, f"Invalid texture ID: '{texture_id}'")
        return jsonify({
            "valid": False,
            "error": "Texture ID must be numeric",
            "server_timestamp": time.time()
        }), 400

    logger.log_processing_start(request_id, texture_id)
    sleeve_color = detect_sleeve_color(texture_id)

    response = {
        "valid": True,
        "color": sleeve_color,
        "sleeve_type": "short",
        "texture_id": texture_id,
        "server_timestamp": time.time()
    }

    processing_time = time.time() - start_time
    logger.log_response(request_id, response)
    logger.log_detection_step(request_id, "Total processing time", f"{processing_time:.3f}s")

    return jsonify(response)

@app.route('/')
def home():
    return "Ultimate Sleeve Detection Server", 200

@app.route('/add_override', methods=['POST'])
def add_override():
    try:
        data = request.json
        texture_id = data.get('texture_id')
        color = data.get('color')

        if not texture_id or not color or len(color) != 3:
            return jsonify({"success": False, "error": "Invalid parameters"}), 400

        SHIRT_OVERRIDES[texture_id] = color
        return jsonify({
            "success": True,
            "message": f"Override added for {texture_id}: {color}",
            "total_overrides": len(SHIRT_OVERRIDES)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
