from waapi import WaapiClient

try:
    client = WaapiClient("ws://127.0.0.1:8080/waapi")
    info = client.call("ak.wwise.core.getInfo")
    print("✅ Connected to Wwise WAAPI!")
    print(info)
except Exception as e:
    print("❌ Cannot connect:", e)

