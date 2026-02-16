import uvicorn
import os
import sys

if __name__ == "__main__":
    # Ensure the root directory is in sys.path
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    print("Starting Server...")
    print("Please make sure you have 'credentials.json' in this folder for Google Sheets to work.")
    
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        print(f"\n✅ Server is running! Access it at: http://{local_ip}:5000\n")
    except Exception:
        print("\nCould not determine local IP. Try accessing via http://localhost:5000\n")

    uvicorn.run("app.main:app", host="0.0.0.0", port=5000, reload=True)
