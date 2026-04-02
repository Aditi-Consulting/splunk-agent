from endpoints.api import app


if __name__ == "__main__":
    print("🚀 Starting Splunk Agent API Server...")
    print("📡 Endpoint: POST http://0.0.0.0:5004/api/v1/splunk-agent?alertId=<id>")
    app.run(host="0.0.0.0", port=5004)
