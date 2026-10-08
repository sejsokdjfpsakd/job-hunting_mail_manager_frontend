import sys
import uuid
import time
from storage import JsonStore
from config import get_settings

def print_help():
    print("Usage: python manage.py [command]")
    print("")
    print("Commands:")
    print("  passkey-setup    生成されたURLから初回ログイン用のパスキーを設定します")
    print("  gen-secrets      .env のシークレットをランダム生成します")

def passkey_setup():
    setup_tokens_store = JsonStore("setup_tokens.json", {})
    token = str(uuid.uuid4())
    now = time.time()
    
    def _save(data):
        data[token] = now
    setup_tokens_store.update(_save)
    
    settings = get_settings()
    url = f"{settings.app_base_url}?setup={token}"
    print(f"以下のURLをブラウザで開いてパスキーを登録してください (15分間有効):")
    print(f"  {url}")

def gen_secrets():
    import secrets
    print("以下の値を .env に設定してください:")
    print(f"API_KEY={secrets.token_urlsafe(32)}")
    print(f"OAUTH_BRIDGE_SECRET={secrets.token_urlsafe(32)}")
    print(f"OAUTH_SIGNING_KEY={secrets.token_urlsafe(32)} (※Vercel環境変数専用)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_help()
    elif sys.argv[1] == "passkey-setup":
        passkey_setup()
    elif sys.argv[1] == "gen-secrets":
        gen_secrets()
    else:
        print("Unknown command:", sys.argv[1])

